extends Node

@onready var agent: CharacterBody3D = get_parent()
@onready var nav_agent: NavigationAgent3D = $"../NavigationAgent3D"
@onready var sensor_system = $"../SensorSystem"

var current_intention: Dictionary = {}
var has_goal: bool = false
var goal_just_reached: bool = false

func _ready():
	nav_agent.velocity_computed.connect(_on_velocity_computed)
	nav_agent.navigation_finished.connect(_on_navigation_finished)
	nav_agent.target_desired_distance = 2.0

func _physics_process(delta):
	if not has_goal:
		return
	
	if nav_agent.is_navigation_finished():
		return
	
	var next_pos = nav_agent.get_next_path_position()
	var direction = (next_pos - agent.global_position).normalized()
	direction.y = 0
	
	var speed = agent.speed
	if current_intention.get("priority", 0.5) > 0.8:
		speed = agent.speed * 1.8
	
	agent.velocity = direction * speed
	
	# Плавный поворот
	if direction.length() > 0.1:
		var look_target = agent.global_position + direction
		look_target.y = agent.global_position.y
		agent.look_at(look_target)

func set_intention(intention: Dictionary):
	if intention == null or intention.is_empty():
		return
	
	current_intention = intention
	var goal = intention.get("goal", "none")
	
	if goal == "none" or goal == "rest":
		has_goal = false
		agent.velocity = Vector3.ZERO
		return
	
	# Найти цель по описанию
	var target_pos = _find_target(intention)
	if target_pos != Vector3.ZERO:
		nav_agent.target_position = target_pos
		has_goal = true
		goal_just_reached = false
		print("🎯 Цель: ", intention.get("description", "?"), " → ", target_pos)
	else:
		# Не нашли конкретную цель — идём в случайном направлении
		var random_dir = Vector3(randf_range(-1, 1), 0, randf_range(-1, 1)).normalized()
		var wander_pos = agent.global_position + random_dir * 15.0
		nav_agent.target_position = wander_pos
		has_goal = true
		goal_just_reached = false
		print("🎯 Бреду: ", intention.get("description", "?"))

func clear_intention():
	current_intention = {}
	has_goal = false
	agent.velocity = Vector3.ZERO

func _find_target(intention: Dictionary) -> Vector3:
	"""Найти позицию цели на основе описания намерения."""
	var goal = intention.get("goal", "")
	var desc = intention.get("description", "").to_lower()
	
	var search_names = []
	
	if goal == "eat" or "яг" in desc or "еда" in desc or "ед" in desc:
		search_names = ["food", "berry", "bush"]
	elif goal == "hide" or "укр" in desc or "пещер" in desc or "спрят" in desc:
		search_names = ["shelter", "cave"]
	elif "вод" in desc or "рек" in desc or "пить" in desc:
		search_names = ["water", "river"]
	elif "дерев" in desc or "лес" in desc:
		search_names = ["tree"]
	elif "камен" in desc or "камн" in desc:
		search_names = ["rock", "stone"]
	elif goal == "investigate" or goal == "explore":
		# Идти к ближайшему видимому объекту
		return _find_nearest_visible_object()
	
	if search_names.is_empty():
		return Vector3.ZERO
	
	# Поиск ближайшего объекта с нужным именем
	var best_dist = 999.0
	var best_pos = Vector3.ZERO
	
	for node in get_tree().get_nodes_in_group("interactable"):
		for sn in search_names:
			if sn in node.name.to_lower():
				var dist = agent.global_position.distance_to(node.global_position)
				if dist < best_dist:
					best_dist = dist
					best_pos = node.global_position
	
	# Если не нашли в группе — поищем по всем StaticBody3D
	if best_pos == Vector3.ZERO:
		for node in get_tree().get_nodes_in_group(""):
			pass
		# Поиск по дереву сцены
		_search_tree(get_tree().root, search_names)
		best_pos = _found_pos
	
	return best_pos

var _found_pos: Vector3 = Vector3.ZERO

func _search_tree(node: Node, search_names: Array):
	for child in node.get_children():
		if child is Node3D:
			for sn in search_names:
				if sn in child.name.to_lower():
					var dist = agent.global_position.distance_to(child.global_position)
					if _found_pos == Vector3.ZERO or dist < agent.global_position.distance_to(_found_pos):
						_found_pos = child.global_position
		_search_tree(child, search_names)

func _find_nearest_visible_object() -> Vector3:
	"""Найти ближайший видимый объект из восприятия."""
	var perception = sensor_system.get_visual_perception()
	var best_dist = 999.0
	var best_dir = Vector3.ZERO
	
	for item in perception:
		if item["object"] != "ничего" and item["object"] != "земля":
			if item["distance"] < best_dist:
				best_dist = item["distance"]
				# Восстановить примерное направление
				var angle = _label_to_angle(item["direction"])
				var dir = agent.global_transform.basis * Vector3(sin(deg_to_rad(angle)), 0, -cos(deg_to_rad(angle)))
				best_dir = agent.global_position + dir * item["distance"]
	
	return best_dir

func _label_to_angle(label: String) -> float:
	match label:
		"далеко слева": return -60.0
		"слева": return -30.0
		"чуть левее": return -15.0
		"впереди": return 0.0
		"чуть правее": return 15.0
		"справа": return 30.0
		"далеко справа": return 60.0
	return 0.0

func _on_velocity_computed(safe_velocity: Vector3):
	agent.velocity = safe_velocity

func _on_navigation_finished():
	has_goal = false
	goal_just_reached = true
	agent.velocity = Vector3.ZERO
	print("✅ Дошёл до цели: ", current_intention.get("description", "?"))
