SERVER_URL = "http://127.0.0.1:8000"
THINK_ENDPOINT = f"{SERVER_URL}/think"
HEALTH_ENDPOINT = f"{SERVER_URL}/health"

# Интервал между тиками мышления (секунды реального времени)
THINK_INTERVAL_SEC = 3.0

# ID симов под управлением Искры (заполняется в рантайме через register_sim)
MANAGED_SIM_IDS: set = set()

# Радиус обнаружения объектов вокруг сима (единицы игры)
PERCEPTION_RADIUS = 10.0
