class IskraLoaderSnippet:
    pass


def _log(msg):
    try:
        with open(r"C:\Users\Alina\Documents\Electronic Arts\The Sims 4\iskra_debug.log", "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

_log("[Искра] __init__.py начал загружаться")

try:
    from . import bridge, control
    _log("[Искра] bridge и control загружены")
except Exception as e:
    _log(f"[Искра] Ошибка импорта bridge/control: {e}")
    import traceback
    _log(traceback.format_exc())
    raise

_register_attempts = 0
_MAX_ATTEMPTS = 10


def _register_active_sim(_=None):
    global _register_attempts
    _register_attempts += 1
    _log(f"[Искра] Попытка регистрации #{_register_attempts}")
    try:
        import services
        sim_info = services.active_sim_info()
        if sim_info is None:
            _schedule_retry()
            return
        sim = sim_info.get_sim_instance()
        if sim is None:
            _schedule_retry()
            return
        control.register_sim(sim)
        _log(f"[Искра] Зарегистрирован: {sim.full_name}")
    except Exception as e:
        _log(f"[Искра] Ошибка регистрации: {e}")
        import traceback
        _log(traceback.format_exc())


def _schedule_retry():
    if _register_attempts >= _MAX_ATTEMPTS:
        return
    try:
        import alarms, clock, services
        alarms.add_alarm(
            services.get_zone(),
            clock.interval_in_real_seconds(2.0),
            _register_active_sim,
            repeating=False,
        )
    except Exception as e:
        _log(f"[Искра] Ретрай не удался: {e}")


def _on_load():
    _log("[Искра] Зона загружена, запускаю мост")
    bridge.start()
    _register_active_sim()


def _on_unload():
    control.unregister_all()
    bridge.stop()


try:
    from sims4communitylib.events.event_handling.common_event_registry import CommonEventRegistry
    from sims4communitylib.events.zone.events.common_zone_loaded_event import CommonZoneLoadedEvent
    from sims4communitylib.events.zone.events.common_zone_unloaded_event import CommonZoneUnloadedEvent

    @CommonEventRegistry.handle_events("iskra_sims")
    def _on_zone_loaded(event: CommonZoneLoadedEvent):
        _on_load()
        return True

    @CommonEventRegistry.handle_events("iskra_sims")
    def _on_zone_unloaded(event: CommonZoneUnloadedEvent):
        _on_unload()
        return True

    _log("[Искра] S4CL хук установлен")

except Exception as e:
    _log(f"[Искра] S4CL недоступен: {e}")
    try:
        import zone as _zone_mod
        _orig_finished = _zone_mod.Zone.on_loading_screen_animation_finished

        def _zone_load_hook(self):
            _orig_finished(self)
            try:
                _on_load()
            except Exception as _exc:
                _log(f"[Искра] on_load ошибка: {_exc}")
                import traceback
                _log(traceback.format_exc())

        _zone_mod.Zone.on_loading_screen_animation_finished = _zone_load_hook
        _log("[Искра] Fallback zone hook установлен")
    except Exception as e2:
        _log(f"[Искра] Fallback zone hook не удался: {e2}")
