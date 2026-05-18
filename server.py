from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import httpx
import json
import re

app = FastAPI()

DEEPSEEK_API_KEY = "-----------"
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
  Ветер: {s.touch.get('wind', '?')}"""


@app.post("/think")
async def think(snapshot: PerceptionSnapshot):
    user_prompt = build_user_prompt(snapshot)
    print(f"\n=== Тик {snapshot.tick} ===")
    print(user_prompt)

    raw = ""
    async with httpx.AsyncClient(timeout=15.0) as client:
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
                    "max_tokens": 1000,
                    "temperature": 0.8
                }
            )
            data = response.json()
            print(f"API STATUS: {response.status_code}")
            print(f"API RESPONSE: {json.dumps(data, ensure_ascii=False)[:500]}")

            if "error" in data:
                print(f"API ERROR: {data['error']}")
                raise Exception(data["error"])

            raw = data["choices"][0]["message"]["content"]
            print(f"RAW: {raw}")

            clean = raw.strip()
            if clean.startswith("```"):
                clean = "\n".join(clean.split("\n")[1:])
                clean = clean.rsplit("```", 1)[0].strip()

            clean = re.sub(r'//.*?(?=\n|$)', '', clean)
            clean = re.sub(r',\s*}', '}', clean)
            clean = re.sub(r',\s*]', ']', clean)

            result = json.loads(clean)
            print(f"💭 {result.get('thought', '...')}")
            print(f"😶 {result.get('emotion', '...')}")

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
    return {"status": "alive"}
