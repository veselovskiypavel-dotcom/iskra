from __future__ import annotations

from .logger import log

_FRIDGE_NAMES  = {"Fridge", "Refrigerator", "FridgeSmall", "FridgeLarge",
                  "object_Fridge", "object_refrigerator"}
_TRASH_NAMES   = {"object_trashcan_outdoor", "object_trashcan_indoor",
                  "TrashCan", "object_garbagecan"}
_BED_NAMES     = {"Bed", "BedDouble", "BedSingle", "BedFull",
                  "object_Bed", "object_bed"}
_SHOWER_NAMES  = {"Shower", "object_ShowerSC1x1_01", "object_shower",
                  "object_bathtub"}
_TV_NAMES      = {"Television", "object_TV", "object_television"}
_TOILET_NAMES  = {"object_toiletC_02", "object_toilet", "object_toiletModern",
                  "object_toiletLid"}


def execute(sim, intention: dict) -> bool:
    # Сервер возвращает либо {"intention": {"goal": ..., "description": ...}, ...}
    # либо {"goal": ..., "description": ...} — пробуем оба формата
    inner = intention.get("intention", intention)
    goal = inner.get("goal", "none")
    desc = inner.get("description", "")
    log(f"[Искра] action.execute: goal={goal!r} desc={desc!r}")

    dispatch = {
        "eat":         _eat,
        "drink":       _eat,
        "rest":        _rest,
        "sleep":       _rest,
        "hygiene":     _hygiene,
        "fun":         _fun,
        "social":      _social,
        "bladder":     _bladder,
        "toilet":      _bladder,
        "explore":     _explore,
        "wander":      _wander,
        "investigate": _investigate,
        "none":        _idle,
    }
    fn = dispatch.get(goal, _idle)
    log(f"[Искра] dispatch → {fn.__name__}")
    return fn(sim) or False


_DEBUG_ONLY = {"debug_Reset", "debug_ObjectDestroy", "cheat_set_as_head"}

_SKIP_NAMES = frozenset({
    "debug_Reset", "debug_ObjectDestroy", "cheat_set_as_head",
    "sim-stand", "fire_ReplaceBurntObject", "object_ReplaceBrokenObject",
})
# "debug" без подчёркивания ловит и debug_Reset, и debugImmediate_rabbitHole
_SKIP_PREFIXES = ("debug", "cheat", "object_Replace", "fire_", "plant_Set", "gardening_",
                  "picker_", "simPicker")  # picker_* / simPicker* открывают UI-окно выбора — блокируют автономию
_SKIP_SUFFIXES = ("Picker", "_picker", "Quality", "_Quality")  # пикеры и debug диалоги качества
# Подстроки в любом месте имени: rabbithole-нора уводит сима из мира (перцепция слепнет)
_SKIP_SUBSTRINGS = ("rabbithole", "rabbit_hole")

# Объекты, которые _investigate не должен выбирать (UI/декор/двери/debug/растения)
_INVESTIGATE_SKIP_KEYWORDS = frozenset((
    "dresser", "wardrobe", "closet", "light_", "door", "wall_",
    "plant", "column", "prototype",
    # Растения и уличная растительность — их affordances часто debug/gardening
    "tree", "flora", "shrub", "bush", "flower", "garden", "grass",
    "weed", "herb", "fern", "succulent", "vine",
))

# Объекты базовых нужд — investigate не трогает, ими управляют специализированные цели
_NEEDS_OBJECT_KEYWORDS = frozenset(("toilet", "fridge", "refrigerat", "bed", "shower", "bathtub"))

def diagnostic_interact(sim) -> None:
    """Форсированная диагностика: находим реальный игровой объект с affordances и пробуем push."""
    import services
    log("[Искра] DIAGNOSTIC_INTERACT: сканируем все объекты")
    all_objs = []
    debug_only_objs = []
    try:
        for obj in services.object_manager().values():
            if obj is sim:
                continue
            aff = getattr(obj, '_super_affordances', None)
            if not aff:
                continue
            aff_names = {getattr(a, '__name__', '') for a in aff}
            if aff_names <= _DEBUG_ONLY:
                debug_only_objs.append(type(obj).__name__)
            else:
                all_objs.append((obj, list(aff)))
    except Exception as e:
        log(f"[Искра] DIAGNOSTIC: ошибка сканирования: {e}")

    log(f"[Искра] DIAGNOSTIC: реальных={len(all_objs)}, debug-only={len(debug_only_objs)}")
    for obj, affs in all_objs[:5]:
        names = [getattr(a, '__name__', type(a).__name__) for a in affs[:4]]
        log(f"[Искра] DIAGNOSTIC: {type(obj).__name__} → {names}")
    if all_objs:
        best_obj = all_objs[0][0]
        _push_first_affordance(sim, best_obj, tag="DIAGNOSTIC")
    elif debug_only_objs:
        log(f"[Искра] DIAGNOSTIC: только debug-объекты ({debug_only_objs[:5]}), пробуем push на первом")
        try:
            first_debug = next(
                o for o in services.object_manager().values()
                if o is not sim and getattr(o, '_super_affordances', None)
            )
            _push_first_affordance(sim, first_debug, tag="DIAGNOSTIC_DEBUG")
        except Exception:
            pass


_PREPARED_FOOD_AFFORDANCES = (
    "food_Eat", "food_EatWithFork", "food_EatSingleServing",
    "food_EatQuickly", "food_EatStanding", "food_EatAtCounter",
    "food_HaveQuickMeal", "food_EatLeftovers",
)

# Готовка открывает picker выбора блюда (блокирует автономию — нужен ручной клик игрока)
# или падает с ошибкой. Исключаем из автономного eat.
_COOK_PICKER_AFFORDANCES = (
    "fridge_Cook", "fridge_CreateTray", "generic_cook",
    "counter_MakeFood_Staging_Basic", "counter_MakeFood_Staging_Gourmet",
)

# Напиток НЕ утоляет голод (наполняет на крохи) и быстро поднимает пузырь.
# Для цели eat не годится — исключаем, иначе сим «ест воду» и зацикливается на туалете.
_DRINK_AFFORDANCES = ("fridge_GrabDrinkAutonomously", "fridge_GrabDrink")


# ═══ МЕНЮ ДЕЙСТВИЙ (гибридный контроль) ═══
# Категория объекта (из perception._identify_object) → (ярлык для LLM, что пушить, что исключить).
# Перцепция строит из этого список «Здесь я могу», LLM выбирает пункт по номеру (action_id),
# а execute_chosen исполняет ровно это действие на КОНКРЕТНОМ объекте (по object_id).
MENU_ACTIONS = {
    "туалет":       ("сходить в туалет",
                     ("generic_ToiletSit", "generic_ToiletStand",
                      "toilet-use-sitting", "toilet-use-standing"), ()),
    "холодильник":  ("взять еду из холодильника",
                     ("fridge_HasLeftovers_Eat", "Dish_Collection_From_Object_As_Dish",
                      "fridge_GrabSnack", "fridge_GrabFood"),
                     _COOK_PICKER_AFFORDANCES + _DRINK_AFFORDANCES),
    "душ":          ("принять душ", ("shower_TakeShower",), ()),
    "ванна":        ("принять ванну", ("bathtub_TakeBath",), ()),
    "кровать":      ("лечь спать", ("bed_sleep", "bed_Nap", "bed_relax_doubleBed"), ()),
    "телевизор":    ("смотреть телевизор",
                     ("TV_Watch", "television_Watch", "object_TV_Watch"), ()),
    "компьютер":    ("сесть за компьютер", ("computer_Play",), ()),
    "книжный шкаф": ("почитать книгу", ("bookcase_ReadBook", "read"), ()),
    "раковина":     ("помыть руки", ("sink_WashHands",), ()),
    "диван":        ("присесть на диван", ("sofa_Sit", "sit"), ()),
    "кресло":       ("сесть в кресло", ("sit",), ()),
    "стул":         ("присесть", ("sit",), ()),
}


def _find_object_by_id(object_id):
    import services
    try:
        mgr = services.object_manager()
        obj = mgr.get(object_id)
        if obj is not None:
            return obj
        for o in mgr.values():
            if getattr(o, "id", None) == object_id:
                return o
    except Exception as e:
        log(f"[Искра] _find_object_by_id: {e}")
    return None


def execute_chosen(sim, chosen: dict) -> bool:
    """Исполняет КОНКРЕТНЫЙ выбор LLM из меню: действие категории на объекте по object_id."""
    category = chosen.get("category")
    obj_id = chosen.get("object_id")
    spec = MENU_ACTIONS.get(category)
    if spec is None or obj_id is None:
        log(f"[Искра] execute_chosen: нет спецификации для {category!r}")
        return False
    label, prefer, exclude = spec
    obj = _find_object_by_id(obj_id)
    if obj is None:
        log(f"[Искра] execute_chosen: объект id={obj_id} ({category}) не найден")
        return False
    log(f"[Искра] execute_chosen → '{label}' на {type(obj).__name__}")
    return _push_first_affordance(sim, obj, tag="choice:" + str(category),
                                  prefer=prefer, exclude=exclude, autonomy=True)

def _eat(sim) -> bool:
    # 1. Готовая еда на тарелках/прилавке — едим сразу, без готовки
    ready = _find_by_affordance(sim, *_PREPARED_FOOD_AFFORDANCES)
    if ready is not None:
        log(f"[Искра] eat → готовая еда: {type(ready).__name__}")
        return _push_first_affordance(sim, ready, tag="eat-ready",
                                      prefer=_PREPARED_FOOD_AFFORDANCES,
                                      autonomy=True)

    # 2. Холодильник — берём готовое/напиток БЕЗ picker.
    #    Готовку (fridge_Cook/CreateTray) исключаем: она открывает окно выбора блюда,
    #    которое замораживает автономию (требует ручного клика игрока).
    fridge = (_find_nearest(sim, _FRIDGE_NAMES, ["fridge", "refrigerat"]) or
              _find_by_affordance(sim, "fridge_GrabSnack", "fridge_GrabFood",
                                  "fridge_HasLeftovers_Eat", "Dish_Collection_From_Object_As_Dish"))
    if fridge is not None:
        result = _push_first_affordance(sim, fridge, tag="eat-fridge",
                                        prefer=("fridge_HasLeftovers_Eat",
                                                "Dish_Collection_From_Object_As_Dish",
                                                "fridge_GrabSnack", "fridge_GrabFood"),
                                        exclude=_COOK_PICKER_AFFORDANCES + _DRINK_AFFORDANCES,
                                        autonomy=True)
        if result:
            return True

    # 3. Мусорка как крайний вариант
    trash = _find_nearest(sim, _TRASH_NAMES, ["trash", "garbage", "trashcan"])
    if trash is not None:
        return _push_first_affordance(sim, trash, tag="eat-trash", autonomy=True)

    # Готовку через picker НЕ запускаем автономно — сим зависнет на окне выбора блюда.
    # На лотах без готовой еды автономный голод закрыть нечем (ограничение лота).
    log("[Искра] eat → автономной еды нет (готовка открыла бы picker — пропускаем)")
    return False


def _rest(sim) -> bool:
    obj = (_find_nearest(sim, _BED_NAMES, ["bed"]) or
           _find_by_affordance(sim, "bed_sleep", "bed_Nap", "bed_relax_doubleBed"))
    if obj is None:
        log("[Искра] rest → кровать не найдена")
        return False
    return _push_first_affordance(sim, obj, tag="rest",
                                  prefer=("bed_sleep", "bed_Nap", "bed_relax_doubleBed"),
                                  autonomy=True)


def _hygiene(sim) -> bool:
    obj = (_find_nearest(sim, _SHOWER_NAMES, ["shower", "bathtub", "bath"]) or
           _find_by_affordance(sim, "shower_TakeShower", "bathtub_TakeBath"))
    if obj is None:
        log("[Искра] hygiene → душ не найден")
        return False
    return _push_first_affordance(sim, obj, tag="hygiene",
                                  prefer=("shower_TakeShower",),
                                  autonomy=True)


def _fun(sim) -> bool:
    obj = (_find_nearest(sim, _TV_NAMES, ["tv", "television"]) or
           _find_by_affordance(sim, "TV_Watch", "television_Watch",
                               "object_TV_Watch", "computer_Play"))
    if obj is None:
        log("[Искра] fun → ТВ не найден")
        return False
    return _push_first_affordance(sim, obj, tag="fun")


_INVESTIGATE_SKIP_EXACT = frozenset({
    "object_light_floor", "object_door", "prototype_RetailCompatible_WallObject",
})

def _has_real_affordances(obj) -> bool:
    """True если у объекта есть хотя бы один не-debug/не-picker affordance."""
    aff = _get_affordances(obj)
    for a in aff:
        name = getattr(a, '__name__', '')
        if (name not in _SKIP_NAMES
                and not any(name.startswith(p) for p in _SKIP_PREFIXES)
                and not any(name.endswith(s) for s in _SKIP_SUFFIXES)
                and not any(sub in name.lower() for sub in _SKIP_SUBSTRINGS)):
            return True
    return False


def _collect_interactable_objects(sim, skip_needs=False):
    """Возвращает список объектов с реальными affordances, пригодных для движения/взаимодействия.
    skip_needs=True исключает объекты базовых нужд (туалет/кровать/холодильник/душ).
    """
    import services
    result = []
    try:
        for obj in services.object_manager().values():
            if obj is sim:
                continue
            # Симы — не «объекты» для движения/исследования (на них висят debug/social/
            # rabbithole-affordances). Социальное взаимодействие идёт отдельным путём.
            if getattr(obj, "is_sim", False):
                continue
            name = type(obj).__name__
            if name in _INVESTIGATE_SKIP_EXACT:
                continue
            name_low = name.lower()
            if any(kw in name_low for kw in _INVESTIGATE_SKIP_KEYWORDS):
                continue
            if skip_needs and any(kw in name_low for kw in _NEEDS_OBJECT_KEYWORDS):
                continue
            if not _has_real_affordances(obj):
                continue
            result.append(obj)
    except Exception as e:
        log(f"[Искра] _collect_interactable: {e}")
    return result


def _investigate(sim) -> bool:
    # Взаимодействуем с ближайшим нетривиальным объектом, не трогаем объекты базовых нужд
    candidates = _collect_interactable_objects(sim, skip_needs=True)
    if not candidates:
        log("[Искра] investigate → объектов не найдено (без нужд)")
        return False
    best = min(candidates, key=lambda o: _dist(sim, o))
    log(f"[Искра] investigate → {type(best).__name__} ({_dist(sim, best):.1f}м)")
    return _push_first_affordance(sim, best, tag="investigate", source="pie_menu",
                                  exclude=_COOK_PICKER_AFFORDANCES)


def _bladder(sim) -> bool:
    obj = (_find_nearest(sim, _TOILET_NAMES, ["toilet"]) or
           _find_by_affordance(sim, "generic_ToiletSit", "generic_ToiletStand",
                               "toilet-use-sitting", "toilet-use-standing",
                               "toilet_use_sitting", "toilet_use_standing"))
    if obj is None:
        log("[Искра] bladder → туалет не найден ни по имени, ни по affordance")
        return False
    _log_positions(sim, obj, "bladder")
    return _push_first_affordance(sim, obj, tag="bladder",
                                  prefer=("generic_ToiletSit", "generic_ToiletStand",
                                          "toilet-use-sitting", "toilet-use-standing"),
                                  autonomy=True)


def _social(sim) -> bool:
    log("[Искра] social → stub (пропускаем)")
    return False


def _wander(sim) -> bool:
    """Идём к случайному объекту на лоте — бесцельное блуждание."""
    import random
    candidates = _collect_interactable_objects(sim, skip_needs=True)
    # Убираем объекты вплотную (<2м) — не топтаться на месте
    candidates = [o for o in candidates if _dist(sim, o) > 2.0]
    if not candidates:
        log("[Искра] wander → нет объектов дальше 2м")
        return False
    obj = random.choice(candidates)
    log(f"[Искра] wander → {type(obj).__name__} ({_dist(sim, obj):.1f}м, случайный)")
    return _push_first_affordance(sim, obj, tag="wander", source="pie_menu",
                                  exclude=_COOK_PICKER_AFFORDANCES)


def _explore(sim) -> bool:
    """Идём к дальнему объекту — сим исследует лот."""
    candidates = _collect_interactable_objects(sim, skip_needs=True)
    # Предпочитаем объекты дальше 5м — шире перемещение по лоту
    far = [o for o in candidates if _dist(sim, o) > 5.0]
    pool = far if far else candidates
    if not pool:
        log("[Искра] explore → нет объектов")
        return False
    # Из пула берём один из топ-3 самых дальних (не всегда самый дальний — разнообразие)
    import random
    pool_sorted = sorted(pool, key=lambda o: _dist(sim, o), reverse=True)
    obj = random.choice(pool_sorted[:3])
    log(f"[Искра] explore → {type(obj).__name__} ({_dist(sim, obj):.1f}м, дальний)")
    return _push_first_affordance(sim, obj, tag="explore", source="pie_menu",
                                  exclude=_COOK_PICKER_AFFORDANCES)


def _idle(sim) -> bool:
    log("[Искра] idle → ничего не делаем")
    return False


def _log_positions(sim, obj, tag=""):
    try:
        sp = sim.position
        op = obj.position
        log(f"[Искра] {tag} позиции: sim=({sp.x:.1f},{sp.y:.1f},{sp.z:.1f}) obj=({op.x:.1f},{op.y:.1f},{op.z:.1f}) dist={_dist(sim,obj):.2f}")
        # Проверяем одинаковый ли routing_surface
        try:
            log(f"[Искра] {tag} surfaces: sim={sim.routing_surface} obj={getattr(obj,'routing_surface','?')}")
        except Exception:
            pass
    except Exception as e:
        log(f"[Искра] _log_positions: {e}")


def _push_first_affordance(sim, obj, tag="action", prefer=(), use_first=False, autonomy=False, source=None, exclude=()) -> bool:
    try:
        context = _make_context(sim, use_first=use_first, autonomy=autonomy,
                                source=source or "script")
        all_aff = _get_affordances(obj)
        if not all_aff:
            log(f"[Искра] {tag} → {type(obj).__name__}: affordances не найдены")
            return False

        # Разделяем на "реальные" и системные/debug/picker
        exclude_set = set(exclude)
        real = [a for a in all_aff
                if getattr(a, '__name__', '') not in _SKIP_NAMES
                and getattr(a, '__name__', '') not in exclude_set
                and not any(getattr(a, '__name__', '').startswith(p) for p in _SKIP_PREFIXES)
                and not any(getattr(a, '__name__', '').endswith(s) for s in _SKIP_SUFFIXES)
                and not any(sub in getattr(a, '__name__', '').lower() for sub in _SKIP_SUBSTRINGS)]
        candidates = real if real else all_aff

        # Предпочитаемые affordances идут первыми (в указанном порядке)
        if prefer:
            pref_order = {name: i for i, name in enumerate(prefer)}
            candidates = sorted(candidates,
                key=lambda a: pref_order.get(getattr(a, '__name__', ''), len(prefer)))

        names = [getattr(a, '__name__', type(a).__name__) for a in candidates[:6]]
        log(f"[Искра] {tag} → {type(obj).__name__}, пробуем: {names}")

        for aff in candidates:
            aff_name = getattr(aff, '__name__', str(aff))
            try:
                result = sim.push_super_affordance(aff, obj, context)
                log(f"[Искра] {tag} → {aff_name}: {result}")
                if result:
                    return True
            except Exception as e:
                log(f"[Искра] {tag} → {aff_name}: ошибка {e}")

        log(f"[Искра] {tag} → все affordances провалились")
        return False
    except Exception as e:
        log(f"[Искра] {tag} → push ошибка: {e}")
        import traceback
        log(traceback.format_exc())
        return False


def _get_affordances(obj):
    """Получаем super affordances объекта — по образцу S4CL CommonObjectInteractionUtils."""
    result = []

    # Способ 1: экземпляр._super_affordances (S4CL использует именно это)
    instance_aff = getattr(obj, '_super_affordances', None)
    if instance_aff:
        result.extend(instance_aff)

    # Способ 2: компоненты с component_super_affordances_gen (S4CL линии 290-300)
    try:
        for component in obj.components:
            if hasattr(component, 'component_super_affordances_gen'):
                for aff in component.component_super_affordances_gen():
                    if aff not in result:
                        result.append(aff)
    except Exception:
        pass

    if not result:
        # Диагностика
        aff_attrs = [m for m in dir(type(obj)) if 'afford' in m.lower() or 'super' in m.lower()]
        log(f"[Искра] affordance диагноз {type(obj).__name__}: {aff_attrs}")
        has_inst = hasattr(obj, '_super_affordances')
        log(f"[Искра]   obj._super_affordances exists: {has_inst}, value: {getattr(obj,'_super_affordances',None)}")

    return result


def _find_by_affordance(sim, *affordance_names: str):
    """Ищем ближайший объект у которого есть хоть один из указанных affordances."""
    import services
    aff_set = set(affordance_names)
    best, best_dist = None, float("inf")
    try:
        for obj in services.object_manager().values():
            if obj is sim:
                continue
            aff = _get_affordances(obj)
            names = {getattr(a, '__name__', '') for a in aff}
            if names & aff_set:
                d = _dist(sim, obj)
                if d < best_dist:
                    best, best_dist = obj, d
    except Exception as e:
        log(f"[Искра] _find_by_affordance: {e}")
    if best is not None:
        log(f"[Искра] _find_by_affordance: {type(best).__name__} ({best_dist:.1f}м)")
    return best


def _find_nearest(sim, type_names: set, keywords=None):
    """Ищем объект: сначала точное совпадение класса, потом частичное по ключевым словам."""
    import services
    best, best_dist = None, float("inf")
    try:
        all_objs = list(services.object_manager().values())
        for obj in all_objs:
            name = type(obj).__name__
            if name in type_names:
                d = _dist(sim, obj)
                if d < best_dist:
                    best, best_dist = obj, d
        if best is None and keywords:
            for obj in all_objs:
                name_low = type(obj).__name__.lower()
                if any(kw in name_low for kw in keywords):
                    d = _dist(sim, obj)
                    if d < best_dist:
                        best, best_dist = obj, d
            if best is not None:
                log(f"[Искра] _find_nearest: частичное совпадение → {type(best).__name__}")
    except Exception as e:
        log(f"[Искра] _find_nearest: {e}")
    return best


def _dist(sim, obj) -> float:
    try:
        return (obj.position - sim.position).magnitude()
    except Exception:
        return float("inf")


def _make_context(sim, use_first=False, autonomy=False, source="script"):
    """source: 'script' | 'autonomy' | 'pie_menu'.
    pie_menu имитирует ручной клик игрока — самый надёжный для маршрутизации,
    т.к. SOURCE_AUTONOMY отбрасывается при отключённой автономии сима.
    """
    from interactions.context import InteractionContext, QueueInsertStrategy
    from interactions.priority import Priority
    strategy = QueueInsertStrategy.FIRST if use_first else QueueInsertStrategy.NEXT
    # autonomy=True исторически означал «надёжный источник» — теперь это pie_menu
    if autonomy and source == "script":
        source = "pie_menu"
    source_map = {
        "autonomy": InteractionContext.SOURCE_AUTONOMY,
        "pie_menu": InteractionContext.SOURCE_PIE_MENU,
        "script":   InteractionContext.SOURCE_SCRIPT,
    }
    ctx_source = source_map.get(source, InteractionContext.SOURCE_SCRIPT)
    return InteractionContext(
        sim,
        ctx_source,
        Priority.High,
        insert_strategy=strategy,
    )
