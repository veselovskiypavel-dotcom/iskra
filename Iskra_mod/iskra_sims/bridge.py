"""
Мост между игрой и сервером мышления.
Весь HTTP — в отдельном потоке-воркере, игровой тик не блокируется.
"""
from __future__ import annotations

import threading
import queue
import urllib.request
import urllib.error
import json
from typing import Optional

from . import config
from .logger import log

# Очередь на 1 слот: всегда отправляем СВЕЖИЙ снимок, старый выбрасываем
_q: queue.Queue = queue.Queue(maxsize=1)

# Последнее полученное намерение, по sim_id
_last_intention: dict = {}
_lock = threading.Lock()

_thread: threading.Thread | None = None
_running = False


def submit_snapshot(sim_id: int, snapshot: dict) -> None:
    """Кладёт снимок в очередь. Неблокирующий — вытесняет старый если очередь полна."""
    payload = {"sim_id": sim_id, "snapshot": snapshot}
    try:
        _q.put_nowait(payload)
    except queue.Full:
        try:
            _q.get_nowait()
        except queue.Empty:
            pass
        try:
            _q.put_nowait(payload)
        except queue.Full:
            pass


def get_last_intention(sim_id: int) -> dict | None:
    """Возвращает последнее готовое намерение для сима (или None)."""
    with _lock:
        return _last_intention.get(sim_id)


def _post_json(url: str, data: dict) -> dict:
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _worker() -> None:
    print("[Искра] Воркер запущен")
    while _running:
        try:
            item = _q.get(timeout=1.0)
        except queue.Empty:
            continue

        sim_id = item["sim_id"]
        snapshot = item["snapshot"]

        try:
            result = _post_json(config.THINK_ENDPOINT, snapshot)
            with _lock:
                _last_intention[sim_id] = result
            goal = result.get('intention', {}).get('goal', '?')
            thought = result.get('thought', '...')[:80]
            log(f"[Искра] ЛЛМ: goal={goal} | {thought}")
        except urllib.error.URLError as e:
            log(f"[Искра] Сервер недоступен: {e.reason}")
        except Exception as e:
            log(f"[Искра] Ошибка воркера: {e}")
            import traceback
            log(traceback.format_exc())


def start() -> None:
    global _thread, _running
    if _thread and _thread.is_alive():
        return
    _running = True
    _thread = threading.Thread(target=_worker, daemon=True, name="iskra_bridge")
    _thread.start()
    print("[Искра] Мост запущен →", config.THINK_ENDPOINT)


def stop() -> None:
    global _running
    _running = False
    print("[Искра] Мост остановлен")


def is_server_alive() -> bool:
    """Быстрая проверка доступности сервера (вызывать из воркера или при старте)."""
    try:
        with urllib.request.urlopen(config.HEALTH_ENDPOINT, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False
