from __future__ import annotations

import re

from . import config
from .logger import log

# Keywords to search in tracker._statistics class names
_NEED_KEYWORDS = {
    "hunger":  ("hunger",),
    "energy":  ("energy", "sleep"),
    "bladder": ("bladder",),
    "hygiene": ("hygiene",),
    "social":  ("social",),
    "fun":     ("fun", "entertainment"),
}

_commodity_errors_logged: set = set()
_all_commodities_logged = False


def _log_all_commodities(sim) -> None:
    global _all_commodities_logged
    if _all_commodities_logged:
        return
    _all_commodities_logged = True
    try:
        all_names = sorted(cls.__name__ for cls in sim.commodity_tracker._statistics.keys())
        log(f"[Искра] все commodities ({len(all_names)}): {all_names}")
    except Exception as e:
        log(f"[Искра] log_all_commodities error: {e}")


def _read_need(sim, *keywords) -> float:
    """Read a need by searching tracker._statistics for class name containing any keyword."""
    try:
        for cls, inst in sim.commodity_tracker._statistics.items():
            name = cls.__name__.lower()
            if any(kw in name for kw in keywords):
                lo = cls.min_value
                hi = cls.max_value
                if hi == lo:
                    return 0.5
                return max(0.0, min(1.0, (inst._value - lo) / (hi - lo)))
    except Exception as e:
        key = str(keywords)
        if key not in _commodity_errors_logged:
            _commodity_errors_logged.add(key)
            log(f"[Искра] _read_need error {keywords}: {e}")
    return 0.5


# ═══ РАСПОЗНАВАНИЕ ОБЪЕКТОВ ═══
# Сырые имена классов движка (object_tvSurfaceLOW1x1_01 и т.п.) непонятны LLM
# и засоряют восприятие дублями. Превращаем их в человеческие категории.
# Порядок важен: первое совпадение по подстроке выигрывает (специфичное — выше).
_OBJECT_RULES = [
    # ── важные интерактивные (★) — закрывают потребности ──
    ("fridge",         "холодильник",       True),
    ("refrigerat",     "холодильник",       True),
    ("stove",          "плита",             True),
    ("microwave",      "микроволновка",     True),
    ("grill",          "гриль",             True),
    ("toilet",         "туалет",            True),
    ("shower",         "душ",               True),
    ("bathtub",        "ванна",             True),
    ("bed",            "кровать",           True),
    ("sink",           "раковина",          True),
    ("tv",             "телевизор",         True),
    ("television",     "телевизор",         True),
    ("computer",       "компьютер",         True),
    ("bookcase",       "книжный шкаф",       True),
    ("stereo",         "музыкальный центр",  True),
    ("door",           "дверь",             True),
    # ── мебель (можно использовать, но не нужда) ──
    ("sofa",           "диван",             False),
    ("loveseat",       "диван",             False),
    ("livingchair",    "кресло",            False),
    ("sit",            "стул",              False),
    ("chair",          "стул",              False),
    ("table",          "стол",              False),
    ("counter",        "кухонная стойка",    False),
    # ── природа / коллекционное (флейвор для размышлений) ──
    ("frog",           "бревно с лягушками", False),
    ("fishingspot",    "место для рыбалки",  False),
    ("fish",           "рыба",              False),
    ("flower",         "цветок",            False),
    ("bush",           "куст",              False),
    ("tree",           "дерево",            False),
    ("gardeningplant", "растение",          False),
    ("plant",          "растение",          False),
    ("rock",           "камень",            False),
    ("stone",          "камень",            False),
    # ── прочее заметное ──
    ("trashcan",       "мусорный бак",       False),
    ("fire_alarm",     "пожарная сигнализация", False),
    ("light",          "светильник",        False),
]

# Объекты-шум: заглушки, декор, отделка — не показываем LLM.
_OBJECT_SKIP = ("prototype", "_deco", "_fx", "footprint", "rug", "curtain", "column")


def _prettify_unknown(class_name: str) -> str:
    """Нераспознанный объект — чистим тех. префиксы/суффиксы, оставляя читаемое имя.
    Так сохраняется emergent-открытие новых объектов, но без мусора движка."""
    s = re.sub(r'^(object_|objects_|collectibles?_|spawners?_|fishing\w*_)', '', class_name, flags=re.I)
    s = re.sub(r'_(public|private|wild|low|high|sc|fc)(?=_|$)', '', s, flags=re.I)
    s = re.sub(r'_?\d+(x\d+)?$', '', s)
    s = s.replace('_', ' ').strip().lower()
    return s or class_name.lower()


def _identify_object(class_name: str):
    """Сырое имя класса → (категория, важный?). None — если объект-шум."""
    low = class_name.lower()
    if any(kw in low for kw in _OBJECT_SKIP):
        return None, False
    for kw, label, important in _OBJECT_RULES:
        if kw in low:
            return label, important
    return _prettify_unknown(class_name), False


def _nearby_objects(sim) -> list:
    """Объекты вокруг, сгруппированные по категориям. Важные (★) — первыми,
    дубли свёрнуты в один пункт со счётчиком, чтобы 9 одинаковых цветов
    не вытесняли холодильник/кровать/ТВ."""
    import services
    groups: dict = {}  # категория → {count, min_dist, important}
    try:
        pos = sim.position
        for obj in services.object_manager().values():
            if obj is sim:
                continue
            try:
                dist = (obj.position - pos).magnitude()
            except Exception:
                continue
            if dist > config.PERCEPTION_RADIUS:
                continue
            label, important = _identify_object(type(obj).__name__)
            if label is None:
                continue
            g = groups.get(label)
            if g is None:
                groups[label] = {"count": 1, "min_dist": dist, "important": important}
            else:
                g["count"] += 1
                g["min_dist"] = min(g["min_dist"], dist)
    except Exception as e:
        log(f"[Искра] Ошибка сбора объектов: {e}")

    # Сортировка: важные первыми, затем по близости
    ordered = sorted(groups.items(),
                     key=lambda kv: (not kv[1]["important"], kv[1]["min_dist"]))
    result = []
    for label, g in ordered[:9]:
        result.append({
            "direction":  "рядом",
            "object":     label,
            "distance":   round(g["min_dist"], 1),
            "important":  g["important"],
            "count":      g["count"],
        })
    return result


# Сырое имя интеракции → человеческий ярлык того, что сим ДЕЛАЕТ сейчас.
# Порядок важен: первое совпадение по подстроке выигрывает.
_ACTION_LABELS = [
    ("watch",  "смотрю телевизор"),
    ("tv",     "смотрю телевизор"),
    ("sleep",  "сплю"),
    ("nap",    "дремлю"),
    ("toilet", "сижу в туалете"),
    ("shower", "принимаю душ"),
    ("bath",   "принимаю ванну"),
    ("eat",    "ем"),
    ("food",   "ем"),
    ("drink",  "пью"),
    ("cook",   "готовлю"),
    ("read",   "читаю"),
    ("chat",   "разговариваю"),
    ("talk",   "разговариваю"),
    ("social", "разговариваю"),
    ("greet",  "здороваюсь"),
    ("dig",    "копаю"),
    ("fish",   "рыбачу"),
    ("route",  "иду"),
    ("goto",   "иду"),
    ("walk",   "иду"),
    ("go_here", "иду"),
    ("sit",    "сижу"),
]

# Интеракции-простой: сим технически «занят», но по сути ничего не делает.
_PASSIVE_ACTIONS = (
    "passive", "_idle", "stand", "noneinteraction", "sim-stand", "emotion_idle",
)


def _build_action_menu(sim) -> list:
    """Меню конкретных действий «Здесь я могу» для гибридного контроля.
    Для каждой видимой категории объекта из action.MENU_ACTIONS — один пункт
    (ближайший объект), с object_id для точного исполнения. LLM выбирает номер."""
    import services
    from . import action  # MENU_ACTIONS — категория → (ярлык, affordances)
    menu = []
    try:
        pos = sim.position
        cands = []
        for obj in services.object_manager().values():
            if obj is sim or getattr(obj, "is_sim", False):
                continue
            try:
                dist = (obj.position - pos).magnitude()
            except Exception:
                continue
            if dist > config.PERCEPTION_RADIUS:
                continue
            cat, _imp = _identify_object(type(obj).__name__)
            if cat not in action.MENU_ACTIONS:
                continue
            cands.append((dist, cat, obj))
        cands.sort(key=lambda x: x[0])
        seen = set()
        idx = 1
        for dist, cat, obj in cands:
            if cat in seen:
                continue
            seen.add(cat)
            menu.append({
                "id":        idx,
                "label":     action.MENU_ACTIONS[cat][0],
                "category":  cat,
                "object_id": getattr(obj, "id", None),
                "distance":  round(dist, 1),
            })
            idx += 1
            if idx > 8:
                break
    except Exception as e:
        log(f"[Искра] _build_action_menu: {e}")
    return menu


def _action_state(sim) -> dict:
    """Что сим делает прямо сейчас: {raw, label, busy}.
    busy=False для простоя/idle — тогда «стою на месте» = реальный провал."""
    try:
        interaction = sim.queue.running
        if interaction is None:
            return {"raw": "ничего", "label": "ничего не делаю", "busy": False}
        raw = type(interaction).__name__
        low = raw.lower()
        is_passive = any(p in low for p in _PASSIVE_ACTIONS)
        label = None
        for kw, human in _ACTION_LABELS:
            if kw in low:
                label = human
                break
        if label is None:
            label = "стою без дела" if is_passive else raw
        return {"raw": raw, "label": label, "busy": not is_passive}
    except Exception:
        return {"raw": "?", "label": "?", "busy": False}


def _world_time(sim) -> str:
    """Реальное время суток из игровых часов."""
    try:
        import services
        now = services.game_clock_service().now()
        hour = now.hour()
        if 5 <= hour < 11:
            return f"утро ({hour:02d}:00)"
        if 11 <= hour < 17:
            return f"день ({hour:02d}:00)"
        if 17 <= hour < 22:
            return f"вечер ({hour:02d}:00)"
        return f"ночь ({hour:02d}:00)"
    except Exception:
        return "день"


# Последняя позиция сима — для детекта реального перемещения
_last_position: dict = {}

# Последние значения потребностей — для трендов (растёт/падает)
_last_needs: dict = {}


def _needs_trend(sim_id, needs: dict) -> dict:
    """Сравнивает потребности с прошлым тиком: какие растут (↑), падают (↓), стоят (=).
    Даёт LLM понять, что текущее действие РАБОТАЕТ (нужная потребность ↑)."""
    prev = _last_needs.get(sim_id)
    _last_needs[sim_id] = dict(needs)
    trend = {}
    if not prev:
        return {k: "=" for k in needs}
    for k, v in needs.items():
        d = v - prev.get(k, v)
        trend[k] = "↑" if d > 0.01 else ("↓" if d < -0.01 else "=")
    return trend


def _movement_since_last(sim) -> dict:
    """Сравнивает позицию с прошлым тиком: двигался ли сим на самом деле."""
    try:
        pos = sim.position
        prev = _last_position.get(sim.id)
        _last_position[sim.id] = (pos.x, pos.y, pos.z)
        if prev is None:
            return {"moved": True, "delta": 0.0}
        dx = pos.x - prev[0]
        dy = pos.y - prev[1]
        dz = pos.z - prev[2]
        delta = (dx * dx + dy * dy + dz * dz) ** 0.5
        return {"moved": delta > 0.3, "delta": round(delta, 2)}
    except Exception:
        return {"moved": True, "delta": 0.0}


def _nearby_sims(sim) -> list:
    """Симы рядом — для социального восприятия."""
    import services
    result = []
    try:
        for sim_info in services.sim_info_manager().values():
            inst = sim_info.get_sim_instance()
            if inst is None or inst is sim:
                continue
            try:
                dist = (inst.position - sim.position).magnitude()
                if dist < 20.0:
                    name = (sim_info.full_name or "незнакомец").strip() or "незнакомец"
                    result.append({"name": name, "distance": round(dist, 1)})
            except Exception:
                pass
    except Exception as e:
        log(f"[Искра] _nearby_sims error: {e}")
    return result


# Объекты, содержащие "fire" в имени, но НЕ являющиеся огнём
# (пожарная сигнализация, спринклер, огнетушитель, дымовой датчик).
# Без этого fire_alarm на стене = вечный фантомный пожар → сим в панике убегает.
_NOT_REAL_FIRE = ("alarm", "sprinkler", "extinguisher", "detector", "smoke")


def _detect_events(sim) -> list:
    """Обнаружение экстренных событий: пожар, дверной звонок."""
    import services
    events = []
    try:
        for obj in services.object_manager().values():
            name_low = type(obj).__name__.lower()
            if "fire" in name_low and not any(fp in name_low for fp in _NOT_REAL_FIRE):
                try:
                    dist = (obj.position - sim.position).magnitude()
                    log(f"[Искра] fire-объект: {type(obj).__name__} ({dist:.1f}м)")
                    events.append({"type": "пожар", "distance": round(dist, 1)})
                except Exception:
                    log(f"[Искра] fire-объект: {type(obj).__name__} (дистанция неизвестна)")
                    events.append({"type": "пожар", "distance": -1})
    except Exception as e:
        log(f"[Искра] _detect_events error: {e}")

    # Дверной звонок — проверяем moodlets или doorbell-состояние
    try:
        for cls, inst in sim.commodity_tracker._statistics.items():
            if "doorbell" in cls.__name__.lower() or "visitor" in cls.__name__.lower():
                events.append({"type": "звонок_в_дверь", "distance": 0})
                break
    except Exception:
        pass

    return events


def collect(sim, tick: int) -> dict:
    if tick == 1:
        _log_all_commodities(sim)

    raw = {k: _read_need(sim, *kws) for k, kws in _NEED_KEYWORDS.items()}

    internal_state = {
        "hunger":          round(raw["hunger"], 2),
        "energy":          round(raw["energy"], 2),
        "fun":             round(raw["fun"], 2),
        "social":          round(raw["social"], 2),
        "hygiene":         round(raw["hygiene"], 2),
        "bladder":         round(raw["bladder"], 2),
        # numeric copies for rule-based fallback
        "hunger_value":    round(raw["hunger"], 2),
        "energy_value":    round(raw["energy"], 2),
        "fun_value":       round(raw["fun"], 2),
    }

    nearby_s = _nearby_sims(sim)
    events    = _detect_events(sim)
    movement  = _movement_since_last(sim)
    action_st = _action_state(sim)
    trend     = _needs_trend(sim.id, {
        "hunger": internal_state["hunger"], "energy": internal_state["energy"],
        "fun": internal_state["fun"], "social": internal_state["social"],
        "hygiene": internal_state["hygiene"], "bladder": internal_state["bladder"],
    })

    menu = _build_action_menu(sim)

    if nearby_s:
        log(f"[Искра] симы рядом: {[s['name'] for s in nearby_s]}")
    if events:
        log(f"[Искра] события: {events}")
    if menu:
        log(f"[Искра] меню: {[(m['id'], m['label']) for m in menu]}")
    log(f"[Искра] движение: delta={movement['delta']}м moved={movement['moved']} "
        f"действие={action_st['raw']} busy={action_st['busy']}")

    return {
        "tick": tick,
        "world_time": _world_time(sim),
        "vision":        _nearby_objects(sim),
        "hearing":       [],
        "touch": {
            "ground":      "пол",
            "temperature": "комфорт",
            "wind":        "нет",
        },
        "internal_state":   internal_state,
        "known_places":     "",
        "nearby_sims":      nearby_s,
        "events":           events,
        "movement":         movement,
        "current_action":   action_st,
        "needs_trend":      trend,
        "available_actions": menu,
    }
