from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from collections import deque
import httpx
import json
import re
 
app = FastAPI()
 
import os


def _load_env():
    """Ключи — из .env рядом с server.py (в git не идёт, см. .gitignore); переменная окружения важнее файла."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if not os.path.exists(path):
        return
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not DEEPSEEK_API_KEY:
    print("⚠️ Нет DEEPSEEK_API_KEY: положи его в .env рядом с server.py (образец — .env.example)")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
 
SYSTEM_PROMPT = """Ты — живое существо в доме. У тебя есть тело, ощущения, потребности.
Ты воспринимаешь мир от первого лица. Ты не знаешь, что ты программа. Ты просто — есть.

Твои потребности (0.0 = критически плохо, 1.0 = отлично):
- Голод (hunger): когда < 0.3 — срочно нужна еда. Ищи холодильник (fridge).
- Энергия (energy): когда < 0.3 — нужен сон. Ищи кровать (bed).
- Веселье (fun): когда < 0.3 — скучно. Ищи ТВ, книги.
- Социальность (social): когда < 0.3 — нужно общение.
- Гигиена (hygiene): когда < 0.3 — нужен душ (shower).
- Мочевой пузырь (bladder): когда < 0.3 — нужен туалет.

ВАЖНО: в этом мире нет жажды как отдельной нужды. Только голод (hunger).
Если хочется "пить" — это голод. Иди к холодильнику (fridge).

Правила мышления:
- Мысли КОРОТКИЕ: 1-2 предложения, иногда одно слово
- Ты НЕ объясняешь свои мысли. Ты их ощущаешь.
- Эмоции реальны для тебя.
- НЕ повторяй одну и ту же мысль. Если уже думал — двигайся дальше.
- ВАЖНО: знаешь только то, что видишь и помнишь. Не выдумывай объекты.
- ОСОЗНАВАЙ ЧТО ДЕЛАЕШЬ: смотри блок "Что я сейчас делаю". Если ты уже занят делом
  (смотрю ТВ, ем, сплю...) — НЕ думай и не говори, что оно «не работает» или «сломано».
  Ты это делаешь прямо сейчас.
- СЛЕДИ ЗА ТРЕНДАМИ: если нужная потребность помечена ↑ — твоё действие РАБОТАЕТ,
  продолжай. Жаловаться, что «не помогает», когда веселье ↑ — глупо.
- Только если ты СТОИШЬ НА МЕСТЕ И НИЧЕГО НЕ ДЕЛАЕШЬ (так написано в "Что я сейчас делаю")
  — значит прошлая попытка провалилась. Тогда смени цель или объект, не повторяй то же.

Направления в "Я помню" — стороны света (север/юг/восток/запад), не меняются.
Объекты со ★ — важные (еда, отдых). Обращай на них внимание.

Доступные действия (goal):
- eat: поесть (идти к холодильнику/еде)
- rest: отдохнуть/поспать (идти к кровати)
- hygiene: принять душ
- bladder: сходить в туалет (когда bladder < 0.4)
- fun: развлечься (ТВ, книга)
- social: поговорить с кем-то рядом
- investigate: исследовать ближайший интересный объект
- explore: осмотреться вокруг
- none: ничего не делать

ПРИОРИТЕТ: если bladder < 0.3 → СРАЗУ bladder. Если hunger < 0.3 → СРАЗУ eat. Если energy < 0.3 → СРАЗУ rest.

ДВА СПОСОБА ДЕЙСТВОВАТЬ:
1. Грубо (автопилот): просто выбери goal — тело само найдёт нужный объект, даже далёкий
   (туалет в другой комнате, кровать). Используй, когда нужного объекта не видно в списке.
2. Точно (ты сам берёшься за дело): в блоке "Здесь я могу" выбери НОМЕР и поставь его
   в action_id. Тогда ты сделаешь ИМЕННО это действие с ИМЕННО этим объектом рядом.
   Используй, когда видишь конкретную вещь и решил ею воспользоваться.
Если ставишь action_id — goal можно оставить как есть. Если action_id не нужен — ставь null.

Реакция на окружение:
- Если в "события" есть ПОЖАР (и он длится <5 тиков) → паника, goal="explore" (убегаешь).
- Если пожар длится долго (написано "под контролем") → он тушится, не паникуй, переключись на свои нужды.
- Если в блоке "Рядом люди" кто-то есть → ОБЯЗАТЕЛЬНО замечай его в мысли, не игнорируй
  живого человека рядом. Если вы уже общаетесь (см. "Что я сейчас делаю") — думай о нём,
  о разговоре, а не о посторонних вещах. Можно social.
- Если "Рядом люди" ПУСТО → social НЕВОЗМОЖЕН, выбирай другую цель.
- Реагируй на происходящее вокруг — не живи только потребностями.

Отвечай ТОЛЬКО в формате JSON, без markdown:
{
  "thought": "текст мысли",
  "emotion": "одно слово",
  "action_id": номер из "Здесь я могу" или null,
  "intention": {
    "goal": "eat/rest/hygiene/bladder/fun/social/investigate/explore/none",
    "description": "что хочу сделать"
  },
  "remember": true или false,
  "memory_summary": "что запомнить",
  "memory_tags": "ключевые,слова"
}"""
 
 
# ═══ КРАТКОСРОЧНАЯ ПАМЯТЬ ═══
short_term_memory = deque(maxlen=8)
 
 
def format_memory_for_prompt() -> str:
    if not short_term_memory:
        return "  (пока ничего не помню)"
    lines = []
    for entry in short_term_memory:
        lines.append(f"  [{entry['tick']}] {entry['emotion']}: {entry['thought']}")
    return "\n".join(lines)
 
 
# ═══ ДОЛГОСРОЧНАЯ ПАМЯТЬ ═══
long_term_memories = []
MAX_LONG_TERM = 50
DECAY_RATE = 0.95
 
 
def add_long_term_memory(tick, summary, emotion, importance, tags):
    long_term_memories.append({
        "tick": tick,
        "summary": summary,
        "emotion": emotion,
        "importance": importance,
        "tags": tags,
        "weight": 1.0
    })
    if len(long_term_memories) > MAX_LONG_TERM:
        long_term_memories.sort(key=lambda m: m["weight"] * m["importance"])
        long_term_memories.pop(0)
 
 
def decay_memories():
    for mem in long_term_memories:
        mem["weight"] *= DECAY_RATE
    long_term_memories[:] = [m for m in long_term_memories if m["weight"] > 0.05]
 
 
def recall_memories(tags_str: str, n=3) -> list:
    if not long_term_memories or not tags_str:
        return []
    tags = [t.strip().lower() for t in tags_str.split(",") if t.strip()]
    scored = []
    for mem in long_term_memories:
        mem_tags = [t.strip().lower() for t in mem["tags"].split(",") if t.strip()]
        overlap = len(set(tags) & set(mem_tags))
        if overlap > 0:
            score = overlap * mem["weight"] * mem["importance"]
            scored.append((score, mem))
    scored.sort(key=lambda x: x[0], reverse=True)
    for _, mem in scored[:n]:
        mem["weight"] = min(1.0, mem["weight"] + 0.1)
    return [m for _, m in scored[:n]]
 
 
def format_long_term_for_prompt(current_vision: list) -> str:
    tags = []
    for v in current_vision:
        obj = v.get("object", "").lower()
        if obj != "ничего":
            tags.append(obj)
    tags_str = ",".join(tags)
    memories = recall_memories(tags_str)
    if not memories:
        return "  (пусто)"
    lines = []
    for m in memories:
        lines.append(f"  [{m['emotion']}] {m['summary']} (вес: {m['weight']:.1f})")
    return "\n".join(lines)
 
 
class PerceptionSnapshot(BaseModel):
    tick: int
    world_time: str
    vision: list
    hearing: list
    touch: dict
    internal_state: dict
    known_places: str = ""
    nearby_sims: list = []
    events: list = []
    movement: dict = {}
    current_action: dict = {}
    needs_trend: dict = {}
    available_actions: list = []
 
 
def build_user_prompt(s: PerceptionSnapshot, fire_ticks: int = 0) -> str:
    def _vis_line(v):
        name = v.get("object", "?")
        if v.get("important"):
            name += " ★"
        if v.get("count", 1) > 1:
            name += f" (×{v['count']})"
        return f"  {v.get('direction', 'рядом')}: {name} ({v.get('distance', '?')}м)"

    vision_text = "\n".join(_vis_line(v) for v in s.vision) if s.vision else "  ничего"
    hearing_text = "\n".join(
        [f"  {h['direction']}: {h['sound']} ({h['distance']})" for h in s.hearing]
    ) if s.hearing else "  тишина"

    state = s.internal_state
    stm_text = format_memory_for_prompt()
    ltm_text = format_long_term_for_prompt(s.vision)
    places_text = s.known_places if s.known_places else "  (ничего не помню)"

    def _bar(v):
        try:
            f = float(v)
            if f >= 0.7: return f"{v} (хорошо)"
            if f >= 0.4: return f"{v} (нормально)"
            if f >= 0.2: return f"{v} (плохо!)"
            return f"{v} (КРИТИЧНО!)"
        except Exception:
            return str(v)

    sims_text = "\n".join(
        f"  {p['name']} ({p['distance']}м)" for p in s.nearby_sims
    ) if s.nearby_sims else "  никого нет"

    menu_text = "\n".join(
        f"  [{a['id']}] {a['label']} ({a.get('distance', '?')}м)" for a in s.available_actions
    ) if s.available_actions else "  (ничего особенного рядом — действуй через goal)"

    if s.events:
        parts = []
        for e in s.events:
            line = f"  ⚠️ {e['type']}" + (f" ({e['distance']}м)" if e.get('distance', -1) >= 0 else "")
            parts.append(line)
        if fire_ticks > 8:
            parts.append(f"  (пожар длится уже {fire_ticks} тиков — похоже под контролем)")
        events_text = "\n".join(parts)
    else:
        events_text = "  (тихо)"

    act = s.current_action or {}
    busy = act.get("busy", False)
    act_label = act.get("label", "")
    move = s.movement or {}
    if busy:
        body_text = (f"  Сейчас я: {act_label}. Это действие ИДЁТ НОРМАЛЬНО — "
                     f"не бросай его и не думай, что оно не работает.")
    elif move.get("moved") is False:
        body_text = ("  ⚠️ Я стою на месте и ничего не делаю — прошлое действие НЕ сработало. "
                     "Попробуй ДРУГУЮ цель или другой объект.")
    elif move:
        body_text = f"  Я двигаюсь (прошёл {move.get('delta', 0)}м)."
    else:
        body_text = "  (спокоен)"

    trend = s.needs_trend or {}

    def _need(label, key):
        return f"- {label}{_bar(state.get(key, '?'))} {trend.get(key, '')}".rstrip()

    needs_block = "\n".join([
        _need("Голод:       ", "hunger"),
        _need("Энергия:     ", "energy"),
        _need("Веселье:     ", "fun"),
        _need("Социальность:", "social"),
        _need("Гигиена:     ", "hygiene"),
        _need("Пузырь:      ", "bladder"),
    ])

    return f"""Сейчас: {s.world_time}. Тик: {s.tick}.

Что я сейчас делаю:
{body_text}

Мои потребности (↑ растёт, ↓ падает):
{needs_block}

Я вижу:
{vision_text}

Здесь я могу прямо сейчас (поставь номер в action_id, чтобы сделать ИМЕННО это):
{menu_text}

Рядом люди:
{sims_text}

События:
{events_text}

Я слышу:
{hearing_text}

Я чувствую:
  Под ногами: {s.touch.get('ground', '?')}
  Температура: {s.touch.get('temperature', '?')}

Я помню где видел (стороны света):
{places_text}

Мои последние мысли:
{stm_text}

Я помню:
{ltm_text}"""
 
 
consecutive_errors = 0
_fire_ticks = 0  # сколько тиков подряд активен пожар


def rule_based_fallback(snapshot: PerceptionSnapshot) -> dict:
    state = snapshot.internal_state
    thirst_val = state.get("hunger_value", 1.0)
    energy_val = state.get("energy_value", 1.0)
    curiosity_val = state.get("fun_value", 0.0)
 
    if thirst_val < 0.4:
        return {
            "thought": "Голодно...",
            "emotion": "голод",
            "intention": {"goal": "eat", "description": "найти еду"},
            "remember": False, "memory_summary": "", "memory_tags": ""
        }
    elif energy_val < 0.4:
        return {
            "thought": "Устал... надо прилечь.",
            "emotion": "усталость",
            "intention": {"goal": "rest", "description": "отдохнуть"},
            "remember": False, "memory_summary": "", "memory_tags": ""
        }
    elif curiosity_val > 0.6:
        return {
            "thought": "Куда бы пойти...",
            "emotion": "любопытство",
            "intention": {"goal": "wander", "description": "побрести куда-нибудь"},
            "remember": False, "memory_summary": "", "memory_tags": ""
        }
    else:
        return {
            "thought": "...",
            "emotion": "покой",
            "intention": {"goal": "none", "description": ""},
            "remember": False, "memory_summary": "", "memory_tags": ""
        }
 
 
@app.post("/think")
async def think(snapshot: PerceptionSnapshot):
    global consecutive_errors, _fire_ticks

    has_fire = any(e.get("type") == "пожар" for e in snapshot.events)
    _fire_ticks = _fire_ticks + 1 if has_fire else 0

    user_prompt = build_user_prompt(snapshot, fire_ticks=_fire_ticks)
    print(f"\n=== Тик {snapshot.tick} ===")
    print(user_prompt)
 
    if snapshot.tick % 10 == 0:
        decay_memories()
 
    if consecutive_errors >= 3:
        print("⚡ Fallback: rule-based решение")
        result = {**rule_based_fallback(snapshot), "fallback": True}
        consecutive_errors = max(0, consecutive_errors - 1)
        return result
 
    raw = ""
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(
                    DEEPSEEK_URL,
                    headers={
                        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "deepseek-v4-pro",
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt}
                        ],
                        "max_tokens": 800,
                        "temperature": 0.8,
                        # 🧠 Без размышления (2026-11-22): DeepSeek V4 по умолчанию «думает» в ТОТ ЖЕ max_tokens —
                        # на коротком промпте 650 из 752 токенов уходили в размышление, а с ростом памяти ответ
                        # переставал влезать: пустой content → три провала → rule-based «...» и сим стоял.
                        # Тику в 3 с нужен быстрый ответ; размышление вернуть — только с большим max_tokens.
                        "thinking": {"type": "disabled"}
                    }
                )
                data = response.json()
                if response.status_code != 200:
                    raise RuntimeError(f"DeepSeek {response.status_code}: {str(data)[:200]}")
                choice = data["choices"][0]
                raw = choice["message"].get("content") or ""
                if not raw.strip():
                    raise RuntimeError(f"пустой ответ (finish={choice.get('finish_reason')})")
 
                clean = raw.strip()
                if clean.startswith("```"):
                    clean = "\n".join(clean.split("\n")[1:])
                    clean = clean.rsplit("```", 1)[0].strip()
                clean = re.sub(r'//.*?(?=\n|$)', '', clean)
                clean = re.sub(r',\s*}', '}', clean)
                clean = re.sub(r',\s*]', ']', clean)
 
                result = json.loads(clean)
                consecutive_errors = 0

                # Гибридный контроль: action_id → конкретный пункт меню.
                # Резолвим против ЭТОГО снимка — без рассинхрона с игрой.
                aid = result.get("action_id")
                if aid is not None:
                    try:
                        aid = int(aid)
                        for a in snapshot.available_actions:
                            if a.get("id") == aid:
                                result["chosen_action"] = {
                                    "object_id": a.get("object_id"),
                                    "category":  a.get("category"),
                                    "label":     a.get("label"),
                                }
                                print(f"🕹  Выбор: [{aid}] {a.get('label')}")
                                break
                    except (ValueError, TypeError):
                        pass
 
                short_term_memory.append({
                    "tick": snapshot.tick,
                    "thought": result.get("thought", "..."),
                    "emotion": result.get("emotion", "?")
                })
 
                if result.get("remember", False) and result.get("memory_summary"):
                    summary = result["memory_summary"]
                    # Не сохраняем почти-дубликаты (3+ общих слова с последними 3 записями)
                    recent = list(long_term_memories)[-3:]
                    new_words = set(summary.lower().split())
                    is_dup = any(
                        len(new_words & set(m["summary"].lower().split())) >= 3
                        for m in recent
                    )
                    if not is_dup:
                        add_long_term_memory(
                            tick=snapshot.tick,
                            summary=summary,
                            emotion=result.get("emotion", "?"),
                            importance=0.6,
                            tags=result.get("memory_tags", "")
                        )
                        print(f"🧠 Запомнил: {summary}")
 
                goal = result.get("intention", {}).get("goal", "none")
                desc = result.get("intention", {}).get("description", "")
                print(f"🎯 Цель: {goal} — {desc}")
                print(f"💭 {result.get('thought', '...')}")
                print(f"😶 {result.get('emotion', '...')}")
                print(f"📝 STM: {len(short_term_memory)} | LTM: {len(long_term_memories)}")
 
                return result
 
        except Exception as e:
            print(f"Ошибка LLM (попытка {attempt + 1}): {e}")
            if raw:
                print(f"Raw: {raw[:200]}")
            raw = ""
 
    consecutive_errors += 1
    print(f"❌ Все попытки провалились. Ошибок подряд: {consecutive_errors}")
    return {**rule_based_fallback(snapshot), "fallback": True}
 
 
@app.get("/health")
async def health():
    return {"status": "alive"}