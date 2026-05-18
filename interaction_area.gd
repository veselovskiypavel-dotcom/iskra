extends Area3D

@onready var internal_state = $"../InternalState"

func _ready():
	body_entered.connect(_on_body_entered)
	area_entered.connect(_on_area_entered)

func _on_body_entered(body: Node3D):
	_try_interact(body)

func _on_area_entered(area: Area3D):
	_try_interact(area)

func _try_interact(node: Node):
	var name = node.name.to_lower()
	
	if "water" in name or "river" in name:
		internal_state.drink(0.4)
		print("💧 Напился! Жажда: ", internal_state.thirst)
	
	elif "food" in name or "berry" in name:
		internal_state.feed(0.3)
		print("🍎 Поел! Энергия: ", internal_state.energy)
	
	elif "shelter" in name or "cave" in name:
		internal_state.safety = min(1.0, internal_state.safety + 0.2)
		print("🏠 В укрытии! Безопасность: ", internal_state.safety)
