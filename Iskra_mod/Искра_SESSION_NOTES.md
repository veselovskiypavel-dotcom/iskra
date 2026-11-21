# Искра-Симс — заметки для продолжения (2026-06-21)

## Текущее состояние

Мод работает, сим регистрируется, LLM получает данные о потребностях, push affordances
технически успешен (`EnqueueResult: True, guaranteed`). Но сим **не доходит до туалета** —
взаимодействие прерывается раньше, чем завершается анимация.

---

## Корневая причина бага с туалетом

**Проблема в `control.py`, функция `_tick`.**

`_clear_queue(sim)` вызывается **перед каждым** `action.execute()`, даже если цель не изменилась.
`investigate` использует `PUSH_COOLDOWN_SHORT = 2` тика.

Что происходит пошагово (из лога):
- Тик 4: `_clear_queue` → `push generic_ToiletSit:6` → (guaranteed) ✓
- Тик 6: `_clear_queue` убивает ToiletSit:6 → `push generic_ToiletSit:8` → (guaranteed) ✓
- Тик 8: `_clear_queue` убивает ToiletSit:8 → push снова...
- И так до тика 14

Анимация туалета (подойти + сесть + использовать) занимает ~5–8+ тиков.
С кулдауном 2 тика сим не успевает завершить её ни разу.

На тике 16 LLM наконец вернул `bladder` (кулдаун 10), и `generic_ToiletSit:18` был запушен.
Но к тому моменту сервер завис (timed out), и мы не видим продолжения лога.

---

## Главный фикс на завтра

**В `control.py`, функция `_tick`:**

```python
# СЕЙЧАС (сломано):
_clear_queue(sim)
action.execute(sim, intention)

# НУЖНО:
if goal_changed:
    _clear_queue(sim)   # прерываем только если цель СМЕНИЛАСЬ
action.execute(sim, intention)
```

Логика: если цель та же (e.g. `investigate` → `investigate`), не прерываем текущее действие —
даём анимации завершиться. Прерываем только когда приходит другая цель.

Также стоит увеличить `PUSH_COOLDOWN_SHORT` для случаев когда `_push_first_affordance`
вернул True (успешный пуш на реальный объект):

```python
# В action.py — _push_first_affordance уже возвращает bool
# В control.py — после execute() если результат True → использовать LONG cooldown
```

Или проще: сделать так, чтобы `investigate` тоже использовал `PUSH_COOLDOWN_LONG` (10),
т.к. он находит реальные объекты (туалет, кровать) и взаимодействует с ними.

---

## Вторичные проблемы

### 1. `investigate` выбирает туалет как "ближайший объект"
Когда сим стоит рядом с туалетом, `_investigate` находит его первым (1.0м).
Это *случайно работает*, но не надёжно — зависит от позиции сима.
Новый `bladder` goal работает правильно и явно.

### 2. `commodity_Motive_Thirst` существует в трекере
Из лога commodities: есть `commodity_Motive_Thirst`, но LLM больше не знает о "жажде" —
убрано из system prompt. Никаких действий не нужно.

### 3. Сервер иногда зависает (timed out в тике 13)
DeepSeek API медленно отвечает. Воркер ждёт 30 сек, потом логирует ошибку и идёт дальше.
Не критично, но замедляет реакцию.

### 4. Холодильник сломан на текущем лоте
`object_ReplaceBrokenObject` — первый affordance у холодильника. Еда не работает.
Чтобы протестировать `eat` goal — починить холодильник в игре или поставить новый.

### 5. `sim.full_name` пустая строка в логах
Косметика — имя сима не отображается. Не мешает работе.

---

## Текущие файлы (актуальное состояние)

### `iskra_sims/control.py`
- Система кулдаунов: `PUSH_COOLDOWN_LONG=10`, `PUSH_COOLDOWN_SHORT=2`
- `_LONG_COOLDOWN_GOALS`: rest/sleep/eat/drink/hygiene/fun/bladder/toilet/social
- `investigate`/`explore`/`wander` → SHORT cooldown (BUG: слишком мало)
- `_clear_queue` вызывается всегда — **это основной баг**

### `iskra_sims/action.py`
- `_bladder()` реализован, ищет туалет по `_TOILET_NAMES` + keyword "toilet"
- `prefer=("generic_ToiletSit", "generic_ToiletStand", ...)` — правильный порядок
- `_investigate` скипает: dresser/wardrobe/closet/light_/door/wall_/plant/column/prototype
- `_SKIP_SUFFIXES=("Picker", "_picker")` — не открываем UI диалоги
- Все 7 целей реализованы: eat/rest/hygiene/bladder/fun/social/investigate+explore

### `iskra_sims/perception.py`
- `_read_need` читает из `sim.commodity_tracker._statistics` по keywords
- Правильно читает: hunger/energy/bladder/hygiene/social/fun
- Значения нормализованы в [0.0, 1.0]

### `server.py`
- `bladder` добавлен в список целей и JSON-формат (добавлено сегодня)
- Строка приоритета: `bladder < 0.3 → bladder`, `hunger < 0.3 → eat`, `energy < 0.3 → rest`
- Model: `deepseek-v4-pro`, max_tokens=800, temperature=0.8
- API key: в .env (DEEPSEEK_API_KEY), не в коде

### Деплой
- `ts4script`: `C:\Users\Alina\Documents\Electronic Arts\The Sims 4\Mods\iskra_sims.ts4script`
- Собирается: `python -c "import zipfile, os; ..."` из папки `Iskra_mod`
- Последний размер: 11300 байт

---

## Plan следующей сессии

1. **Главный фикс**: в `control.py` → `_tick()` — `_clear_queue` только при `goal_changed`
2. **Тест туалета**: после фикса — убедиться что сим реально садится и встаёт
3. **Тест еды**: починить холодильник, проверить что `eat` goal работает
4. **Опционально**: заставить `explore`/`wander` делать что-то реальное (идти к случайному объекту)
   вместо просто остановки очереди
5. **Опционально**: `_investigate` возвращать `True/False` из `_push_first_affordance`
   и если True — использовать `PUSH_COOLDOWN_LONG` автоматически

---

## Как запустить

1. Запустить `server.py`: `cd Iskra_mod && uvicorn server:app --reload --port 8000`
2. Запустить The Sims 4
3. Загрузить сохранение (одиночный сим дома)
4. Лог: `%USERPROFILE%\Documents\Electronic Arts\The Sims 4\Logs\iskra_debug.log`
