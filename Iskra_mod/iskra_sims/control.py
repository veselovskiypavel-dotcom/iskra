from __future__ import annotations

from . import bridge, perception, action, config, display
from .logger import log

_managed: dict = {}
_tick_counter = 0
_last_goal: dict = {}           # sim_id → последняя отправленная цель
_push_cooldown_until: dict = {} # sim_id → тик когда кулдаун истекает
# Долгие действия (нужно время дойти и выполнить)
_LONG_COOLDOWN_GOALS = frozenset({"rest", "sleep", "eat", "drink", "hygiene", "fun", "bladder", "toilet", "social"})
PUSH_COOLDOWN_LONG  = 10  # ~50 сек — дойти + выполнить анимацию
PUSH_COOLDOWN_SHORT = 2   # ~10 сек — для explore/investigate/wander
PROTECT_TICKS       = 10  # столько тиков долгое действие защищено от перебивания др. целью
_protect_until: dict = {} # sim_id → тик до которого нельзя сменить цель (даём маршруту дойти)


def register_sim(sim) -> None:
    import alarms
    import clock

    sim_id = sim.id
    if sim_id in _managed:
        print(f"[Искра] {sim.full_name} уже зарегистрирован")
        return

    _disable_autonomy(sim)
    log(f"[Искра] register_sim: автономия отключена для {sim.full_name}")

    handle = alarms.add_alarm(
        sim,
        clock.interval_in_real_seconds(config.THINK_INTERVAL_SEC),
        lambda _: _tick(sim),
        repeating=True,
        cross_zone=False,
    )
    _managed[sim_id] = {"alarm": handle, "sim": sim}
    config.MANAGED_SIM_IDS.add(sim_id)
    print(f"[Искра] ✅ {sim.full_name} зарегистрирован")


def unregister_sim(sim) -> None:
    import alarms

    sim_id = sim.id
    entry = _managed.pop(sim_id, None)
    if entry is None:
        return
    alarms.cancel_alarm(entry["alarm"])
    _enable_autonomy(sim)
    config.MANAGED_SIM_IDS.discard(sim_id)
    print(f"[Искра] {sim.full_name} освобождён")


def unregister_all() -> None:
    for entry in list(_managed.values()):
        unregister_sim(entry["sim"])


_note_goal: dict = {}   # sim_id → цель, на которой показали уведомление
_note_at: dict = {}     # sim_id → когда (time.time)


def _tick(sim) -> None:
    global _tick_counter
    _tick_counter += 1

    # Форсированная диагностика affordances на тике 1
    if _tick_counter == 1:
        try:
            action.diagnostic_interact(sim)
        except Exception as _e:
            log(f"[Искра] diagnostic_interact ошибка: {_e}")

    # Аварийный выход из rabbithole-норы: сим исчезает из мира, перцепция слепнет,
    # время летит. Не должно случаться (фильтры в action.py), но если попал — вытаскиваем.
    try:
        running = sim.queue.running
        if running is not None and "rabbithole" in type(running).__name__.lower():
            log("[Искра] ⚠️ сим в rabbithole — принудительный выход")
            _clear_queue(sim)
            _last_goal[sim.id] = None  # сбросить, чтобы следующая цель точно перепушилась
            _protect_until[sim.id] = 0  # снять защиту — нора не «защищённое действие»
    except Exception:
        pass

    snapshot = perception.collect(sim, _tick_counter)
    bridge.submit_snapshot(sim.id, snapshot)
    intention = bridge.get_last_intention(sim.id)

    # Диагностика очереди
    try:
        running = sim.queue.running
        queue_list = list(sim.queue)
        running_name = type(running).__name__ if running else "None"
        pending = [type(i).__name__ for i in queue_list if i is not running]
        log(f"[Искра] Тик {_tick_counter}: queue running={running_name}, pending={pending}")
    except Exception:
        pass

    if not intention:
        log(f"[Искра] Тик {_tick_counter}: намерение=None")
        return

    # Канал МЫСЛЕЙ (только для нас) — показываем до любых return по кулдауну.
    # Дедуп внутри display: одна мысль висит, пока не сменится.
    try:
        # Запасной ответ сервера (модель не ответила) — не мысль сима: не показываем.
        # 🎬 Все мысли — в оверлее сервера (/thoughts); в игре — только при смене цели и не чаще THOUGHT_NOTE_SEC:
        # доска уведомлений переполнялась, и новые мысли переставали появляться (2026-11-22).
        if not intention.get("fallback") and config.THOUGHTS_IN_GAME:
            import time as _t
            g = (intention.get("chosen_action") or {}).get("category") or (intention.get("intention") or {}).get("goal")
            if g != _note_goal.get(sim.id) and _t.time() - _note_at.get(sim.id, 0) >= config.THOUGHT_NOTE_SEC:
                _note_goal[sim.id] = g
                _note_at[sim.id] = _t.time()
                display.show_thought(sim, intention.get("thought", ""), intention.get("emotion", ""))
    except Exception as _e:
        log(f"[Искра] display.show_thought: {_e}")

    sim_id = sim.id

    # Гибридный контроль: если LLM выбрал конкретный пункт меню (action_id),
    # исполняем ИМЕННО его. Иначе — грубый автопилот по goal.
    chosen = intention.get("chosen_action") if isinstance(intention, dict) else None
    if chosen and chosen.get("object_id") is not None:
        new_goal = "act:" + str(chosen.get("category", "?"))
        is_long = True  # осознанный выбор защищаем как долгое действие
    else:
        chosen = None
        inner = intention.get("intention", intention)
        new_goal = inner.get("goal", "none")
        is_long = new_goal in _LONG_COOLDOWN_GOALS

    prev_goal = _last_goal.get(sim_id)

    # «Ничего» = продолжаю, что делаю: очередь не трогаем (раньше смена цели на none рвала телевизор).
    # Цель, которую сим уже исполняет (спит, а просят «спать» или «кровать»), — тоже продолжение, а не новая цель:
    # раньше rest → act:кровать считалась сменой, очередь чистилась, и сон перезапускался.
    if new_goal == "none" or _already_doing(sim, new_goal):
        if new_goal != "none":
            _last_goal[sim_id] = new_goal
        log(f"[Искра] Тик {_tick_counter}: {new_goal!r} — продолжаю текущее занятие, ничего не толкаю")
        return

    goal_changed = new_goal != prev_goal

    # ЗАЩИТА ДОЛГОГО ДЕЙСТВИЯ: пока сим идёт в туалет/к кровати/есть — не даём LLM
    # перебить это другой целью. Иначе при метании целей (bladder→explore→…)
    # _clear_queue убивает ещё не достроенный маршрут, и сим никогда не доходит.
    if goal_changed and _tick_counter < _protect_until.get(sim_id, 0):
        log(f"[Искра] Тик {_tick_counter}: {new_goal!r} игнорирован — "
            f"идёт защищённое действие {prev_goal!r} (до тика {_protect_until[sim_id]})")
        return

    # Кулдаун: не повторяем тот же goal пока не истечёт время
    in_cooldown = (not goal_changed and
                   _tick_counter < _push_cooldown_until.get(sim_id, 0))

    if in_cooldown:
        log(f"[Искра] Тик {_tick_counter}: {new_goal!r} кулдаун до тика {_push_cooldown_until[sim_id]}")
        return

    cooldown = PUSH_COOLDOWN_LONG if is_long else PUSH_COOLDOWN_SHORT

    # Цель та же, кулдаун истёк, но сим ещё выполняет действие — продлеваем, не перебиваем
    if not goal_changed and _is_sim_busy(sim):
        _push_cooldown_until[sim_id] = _tick_counter + cooldown
        log(f"[Искра] Тик {_tick_counter}: {new_goal!r} — сим занят, кулдаун продлён до {_push_cooldown_until[sim_id]}")
        return

    # Если сим занят реальным действием — короткие цели не прерывают (не будим сон ради "исследовать")
    # Но длинные/срочные (bladder, eat, hygiene...) — прерывают (будим когда надо в туалет)
    if goal_changed and _is_sim_busy(sim) and not is_long:
        _push_cooldown_until[sim_id] = _tick_counter + PUSH_COOLDOWN_LONG
        try:
            running_name = type(sim.queue.running).__name__
        except Exception:
            running_name = "?"
        log(f"[Искра] Тик {_tick_counter}: {new_goal!r} игнорирован — сим занят ({running_name}), кулдаун до {_push_cooldown_until[sim_id]}")
        return

    log(f"[Искра] Тик {_tick_counter}: goal={new_goal!r} prev={prev_goal!r} (пушим)")
    if goal_changed:
        _clear_queue(sim)
    if chosen:
        pushed = action.execute_chosen(sim, chosen)
    else:
        pushed = action.execute(sim, intention)
    _last_goal[sim_id] = new_goal
    # Если push успешен — всегда LONG кулдаун: дать время дойти и выполнить анимацию
    _push_cooldown_until[sim_id] = _tick_counter + (PUSH_COOLDOWN_LONG if pushed else cooldown)
    # Долгое/срочное/осознанное действие защищаем от перебивания другой целью на PROTECT_TICKS
    if pushed and is_long:
        _protect_until[sim_id] = _tick_counter + PROTECT_TICKS
    log(f"[Искра] Тик {_tick_counter}: pushed={pushed}, кулдаун до тика {_push_cooldown_until[sim_id]}")


def _disable_autonomy(sim) -> None:
    comp = sim.autonomy_component
    # Прямой атрибут _autonomy_enabled (виден в dir())
    try:
        comp._autonomy_enabled = False
        log("[Искра] _autonomy_enabled = False установлен")
    except Exception as e:
        log(f"[Искра] _autonomy_enabled не сработал: {e}")
    # Дополнительно — отменяем текущий активный запрос автономии
    try:
        comp.cancel_actively_running_full_autonomy_request()
        log("[Искра] cancel_actively_running_full_autonomy_request OK")
    except Exception as e:
        log(f"[Искра] cancel_request: {e}")


def _enable_autonomy(sim) -> None:
    try:
        from autonomy.settings import AutonomyMode
        sim.autonomy_component.set_autonomy_mode(AutonomyMode.FULL_AUTONOMY)
    except Exception as e:
        print(f"[Искра] Не удалось включить автономию: {e}")


_PASSIVE_INTERACTIONS = frozenset({
    "stand_Passive", "sim-stand", "NoneInteraction",
    # Сидеть/смотреть без дела — тоже idle, не мешают новым командам
    "sit_Passive", "Emotion_Idle", "toilet-flush",
    "watch-passive", "watch-sports", "watch-sports2", "watch-passive-withphone",
})

def _is_sim_busy(sim) -> bool:
    """True если сим занят настоящим делом. Мерка одна с восприятием (perception._action_state):
    sleep_Passive / watch-passive — это сон и телевизор, а не простой (2026-11-22)."""
    try:
        return bool(perception._action_state(sim).get("busy"))
    except Exception:
        return False


# Какое занятие (ярлык perception._action_state) уже исполняет цель — повторять её не нужно.
_ACTIVITY_OF_GOAL = {
    "rest": ("сплю", "дремлю"), "sleep": ("сплю", "дремлю"), "act:кровать": ("сплю", "дремлю"),
    "eat": ("ем",), "act:холодильник": ("ем",),
    "hygiene": ("принимаю душ", "принимаю ванну"), "act:душ": ("принимаю душ",), "act:ванна": ("принимаю ванну",),
    "bladder": ("сижу в туалете",), "toilet": ("сижу в туалете",), "act:туалет": ("сижу в туалете",),
    "fun": ("смотрю телевизор", "читаю"), "act:телевизор": ("смотрю телевизор",), "act:книжный шкаф": ("читаю",),
    "social": ("разговариваю",),
    "act:диван": ("сижу",), "act:кресло": ("сижу",), "act:стул": ("сижу",),
}


def _already_doing(sim, goal) -> bool:
    """Сим уже занят тем, чего просит цель (спит, а цель «спать» или «кровать»)."""
    try:
        st = perception._action_state(sim)
        return bool(st.get("busy")) and st.get("label") in _ACTIVITY_OF_GOAL.get(goal, ())
    except Exception:
        return False


def _clear_queue(sim) -> None:
    try:
        from interactions.interaction_finisher import FinishingType
        for interaction in list(sim.queue):
            try:
                # USER_CANCEL корректно останавливает сон/анимации; KILLED — запасной вариант
                interaction.cancel(FinishingType.USER_CANCEL, cancel_reason_msg='iskra')
            except Exception:
                try:
                    interaction.cancel(FinishingType.KILLED, cancel_reason_msg='iskra')
                except Exception:
                    pass
    except Exception:
        try:
            sim.queue.clear()
        except Exception:
            pass
