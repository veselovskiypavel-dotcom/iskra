extends Area3D

@onready var internal_state = $"../InternalState"

# Кулдаун чтобы не спамить взаимодействиями
var _interact_cooldown: float = 0.0
var COOLDOWN_TIME: float = 2.0  # секунды между взаимодействиями

func _physics_process(delta):
	_interact_cooldown -= delta
	if _interact_cooldown > 0.0:
		return
	
	# Проверяем всё что перекрывается с нашей областью
	for body in get_overlapping_bodies():
		if _try_interact(body):
			return
	
	for area in get_overlapping_areas():
		if _try_interact(area):
			return

func _try_interact(node: Node) -> bool:
	var node_name = node.name.to_lower()
	
	if "water" in node_name or "river" in node_name:
		internal_state.drink(0.4)
		internal_state.register_stimulus()
		_interact_cooldown = COOLDOWN_TIME
		print("💧 Напился! Жажда: %.2f" % internal_state.thirst)
		return true
	
	elif "food" in node_name or "berry" in node_name:
		internal_state.feed(0.3)
		internal_state.register_stimulus()
		_interact_cooldown = COOLDOWN_TIME
		print("🍎 Поел! Энергия: %.2f" % internal_state.energy)
		return true
	
	elif "shelter" in node_name or "cave" in node_name:
		internal_state.safety = min(1.0, internal_state.safety + 0.2)
		internal_state.register_stimulus()
		_interact_cooldown = COOLDOWN_TIME
		print("🏠 В укрытии! Безопасность: %.2f" % internal_state.safety)
		return true
	
	return false
