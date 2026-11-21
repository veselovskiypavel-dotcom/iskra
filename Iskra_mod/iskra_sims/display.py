"""Визуализация Искры в игре. Два РАЗНЫХ канала:

1. МЫСЛИ (show_thought) — внутренний монолог, виден ТОЛЬКО нам (наблюдателю).
   Угловое уведомление с портретом сима. НЕ часть восприятия других симов.
   ← реализовано.

2. РЕЧЬ (show_speech) — то, что сим ПРОИЗНОСИТ; её воспринимают другие
   управляемые симы (с другой LLM) через сервер. Пузырь над головой +
   запись в восприятие собеседника. Сердце Модуля 4 (диалог двух агентов).
   ← TODO, отдельная задача (нужен overhead-balloon + обратная связь в perception).

Пузырь над головой в Sims 4 требует игрового модуля balloon с тюнингом —
ненадёжно, поэтому для мыслей используем notification из S4CL.

ВАЖНО: вызывать ТОЛЬКО из игрового потока (тик/alarm),
UI-вызовы из воркер-потока моста недопустимы.
"""
from __future__ import annotations

from .logger import log

# sim_id → последняя показанная мысль (дедуп: одна мысль висит до смены)
_last_shown: dict = {}


def show_thought(sim, thought: str, emotion: str = "") -> None:
    """Показывает мысль сима уведомлением. Если мысль не изменилась — молчит."""
    if not thought:
        return
    sim_id = getattr(sim, "id", None)
    if _last_shown.get(sim_id) == thought:
        return  # та же мысль — не спамим уведомлениями
    _last_shown[sim_id] = thought

    try:
        from sims4communitylib.notifications.common_basic_notification import CommonBasicNotification
        from distributor.shared_messages import IconInfoData

        title = (f"💭 {emotion}".strip()) if emotion else "💭"
        notification = CommonBasicNotification(title, thought)

        icon = None
        try:
            icon = IconInfoData(obj_instance=sim)  # портрет сима
        except Exception:
            icon = None

        notification.show(icon=icon)
    except Exception as e:
        log(f"[Искра] show_thought ошибка: {e}")


def reset() -> None:
    """Сброс дедупа (например при перезагрузке зоны)."""
    _last_shown.clear()
