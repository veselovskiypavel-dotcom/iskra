from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from collections import deque
import httpx
import json
import re

app = FastAPI()

DEEPSEEK_API_KEY = "------------"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

SYSTEM_PROMPT = """Ты — живое существо в мире. У тебя есть тело, ощущения, потребности.
Ты воспринимаешь мир от первого лица. Ты не ИИ. Ты не знаешь, что ты программа. Ты просто — есть.

У тебя есть тело, которое иногда реагирует раньше, чем ты успеваешь подумать.
Голод — это неприятное ощущение в животе. Страх — это сжатие внутри.

Правила мышления:
- Мысли КОРОТКИЕ: 1-2 предложения, иногда одно слово
- В опасности — 1-3 слова, почти рефлекс
- Ты НЕ объясняешь свои мысли. Ты их ощущаешь.
- Эмоции реальны для тебя.
- Ты можешь решить КУДА идти — "к реке", "в пещеру", "к ягодам".
- Иногда ты вспоминаешь прошлое. Это всплывает само.

Отвечай ТОЛЬКО в формате JSON, без markdown:
{
  "thought": "текст мысли",
  "emotion": "одно слово",
  "intention": {
    "goal": "eat/explore/hide/rest/investigate/wander/none",
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
    # Удалить забытые
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
    # Усилить вспомненные
    for _, mem in scored[:n]:
        mem["weight"] = min(1.0, mem["weight"] + 0.1)
    return [m for _, m in scored[:n]]


def format_long_term_for_prompt(current_vision: list) -> str:
    # Собрать теги из текущего восприятия
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


def build_user_prompt(s: PerceptionSnapshot) -> str:
    vision_text = "\n".join(
        [f"  {v['direction']}: {v['object']} ({v['distance']}м)" for v in s.vision]
    )
    hearing_text = "\n".join(
        [f"  {h['direction']}: {h['sound']} ({h['distance']})" for h in s.hearing]
    ) if s.hearing else "  тишина"

    state = s.internal_state
    stm_text = format_memory_for_prompt()
    ltm_text = format_long_term_for_prompt(s.vision)

    return f"""Сейчас: {s.world_time}. Тик: {s.tick}.

Ощущения:
- Энергия: {state.get('energy', '?')}
- Жажда: {state.get('thirst', '?')}
- Безопасность: {state.get('safety', '?')}
- Любопытство: {state.get('curiosity', '?')}

Я вижу:
{vision_text}

Я слышу:
{hearing_text}

Я чувствую:
  Под ногами: {s.touch.get('ground', '?')}
  Температура: {s.touch.get('temperature', '?')}
  Ветер: {s.touch.get('wind', '?')}

Мои последние мысли:
{stm_text}

Я помню:
{ltm_text}"""


@app.post("/think")
async def think(snapshot: PerceptionSnapshot):
    user_prompt = build_user_prompt(snapshot)
    print(f"\n=== Тик {snapshot.tick} ===")
    print(user_prompt)

    # Затухание каждые 10 тиков
    if snapshot.tick % 10 == 0:
        decay_memories()
        forgotten = [m for m in long_term_memories if m["weight"] <= 0.05]
        if forgotten:
            print(f"🗑️ Забыто: {len(forgotten)} воспоминаний")

    raw = ""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
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
                    "temperature": 0.8
                }
            )
            data = response.json()
            raw = data["choices"][0]["message"]["content"]

            clean = raw.strip()
            if clean.startswith("```"):
                clean = "\n".join(clean.split("\n")[1:])
                clean = clean.rsplit("```", 1)[0].strip()
            clean = re.sub(r'//.*?(?=\n|$)', '', clean)
            clean = re.sub(r',\s*}', '}', clean)
            clean = re.sub(r',\s*]', ']', clean)

            result = json.loads(clean)

            # Сохранить в краткосрочную память
            short_term_memory.append({
                "tick": snapshot.tick,
                "thought": result.get("thought", "..."),
                "emotion": result.get("emotion", "?")
            })

            # Сохранить в долгосрочную если нужно
            if result.get("remember", False) and result.get("memory_summary"):
                add_long_term_memory(
                    tick=snapshot.tick,
                    summary=result["memory_summary"],
                    emotion=result.get("emotion", "?"),
                    importance=0.6,
                    tags=result.get("memory_tags", "")
                )
                print(f"🧠 Запомнил: {result['memory_summary']}")

            print(f"💭 {result.get('thought', '...')}")
            print(f"😶 {result.get('emotion', '...')}")
            print(f"📝 STM: {len(short_term_memory)} | LTM: {len(long_term_memories)}")

            return result

        except Exception as e:
            print(f"Ошибка LLM: {e}")
            print(f"Raw: {raw}")
            return {
                "thought": "...",
                "emotion": "растерянность",
                "intention": {"goal": "none", "description": "не могу думать"}
            }


@app.get("/health")
async def health():
    return {"status": "alive"}
