extends Node

@onready var agent: CharacterBody3D = get_parent()
@onready var nav_agent: NavigationAgent3D = $"../NavigationAgent3D"
@onready var sensor_system = $"../SensorSystem"

var current_intention: Dictionary = {}
var has_goal: bool = false
var goal_just_reached: bool = false

var _last_position: Vector3 = Vector3.ZERO
var _stuck_timer: float = 0.0
var _stuck_threshold: float = 4.0
var _stuck_attempts: int = 0

var _goal_priority: Dictionary = {
	"none": 0, "rest": 0, "wander": 1, "explore": 2,
	"investigate": 3, "eat": 5, "drink": 5, "hide": 6,
}

var _interactable_goals: Array = ["eat", "drink", "hide"]

func _ready():
	nav_agent.navigation_finished.connect(_on_navigation_finished)
	nav_agent.target_desired_distance = 1.5
	nav_agent.avoidance_enabled = false
	nav_agent.path_desired_distance = 1.0

func _physics_process(delta):
	if agent.player_controlled:
		has_goal = false
		return
	if not has_goal or nav_agent.is_navigation_finished():
		return
	
	var current_pos = agent.global_position
	if current_pos.distance_to(_last_position) < 0.15:
		_stuck_timer += delta
		if _stuck_timer > _stuck_threshold:
			_unstuck()
			return
	else:
		_stuck_timer = 0.0
		_stuck_attempts = 0
	_last_position = current_pos
	
	var next_pos = nav_agent.get_next_path_position()
	var direction = (next_pos - agent.global_position)
	direction.y = 0
	direction = direction.normalized()
	if direction.length() < 0.01:
		return
	
	var speed = agent.speed
	if current_intention.get("goal", "") in _interactable_goals:
		speed = agent.speed * 1.4
	
	agent.velocity.x = direction.x * speed
	agent.velocity.z = direction.z * speed
	
	var look_target = agent.global_position + direction
	look_target.y = agent.global_position.y
	agent.look_at(look_target)

func _unstuck():
	_stuck_timer = 0.0
	_stuck_attempts += 1
	if _stuck_attempts >= 4:
		_stuck_attempts = 0
		has_goal = false
		goal_just_reached = true
		agent.velocity.x = 0
		agent.velocity.z = 0
		print("⚠️ Не могу дойти, сдаюсь: ", current_intention.get("description", "?"))
		return
	var angle = (PI / 2.0) * _stuck_attempts
	var escape_dir = agent.global_transform.basis.x.rotated(Vector3.UP, angle)
	var escape_pos = agent.global_position + escape_dir * 6.0
	nav_agent.target_position = escape_pos
	has_goal = true
	print("⚠️ Застрял (попытка %d), обхожу..." % _stuck_attempts)

func set_intention(intention: Dictionary):
	if agent.player_controlled:
		return
	if intention == null or intention.is_empty():
		return
	var new_goal = intention.get("goal", "none")
	var old_goal = current_intention.get("goal", "none")
	
	if has_goal and not goal_just_reached:
		var new_prio = _goal_priority.get(new_goal, 2)
		var old_prio = _goal_priority.get(old_goal, 2)
		if new_goal == old_goal:
			return
		if new_prio <= old_prio:
			return
		print("🔄 Смена цели: ", old_goal, " → ", new_goal)
	
	current_intention = intention
	if new_goal == "none" or new_goal == "rest":
		has_goal = false
		agent.velocity.x = 0
		agent.velocity.z = 0
		return
	
	var target_pos = _find_target(intention)
	if target_pos != Vector3.ZERO:
		var approach_pos = target_pos
		if new_goal not in _interactable_goals:
			var offset = (agent.global_position - target_pos).normalized() * 3.0
			offset.y = 0
			approach_pos = target_pos + offset
		nav_agent.target_position = approach_pos
		has_goal = true
		goal_just_reached = false
		_stuck_timer = 0.0
		_stuck_attempts = 0
		print("🎯 Цель: ", intention.get("description", "?"), " → ", approach_pos)
	else:
		_wander(intention)

func _wander(intention: Dictionary):
	var forward = -agent.global_transform.basis.z
	var random_angle = randf_range(-PI / 3.0, PI / 3.0)
	var wander_dir = forward.rotated(Vector3.UP, random_angle)
	wander_dir.y = 0
	wander_dir = wander_dir.normalized()
	var wander_pos = agent.global_position + wander_dir * randf_range(10.0, 25.0)
	nav_agent.target_position = wander_pos
	has_goal = true
	goal_just_reached = false
	_stuck_timer = 0.0
	_stuck_attempts = 0
	print("🎯 Бреду: ", intention.get("description", "?"))

func clear_intention():
	current_intention = {}
	has_goal = false
	agent.velocity.x = 0
	agent.velocity.z = 0

func _find_target(intention: Dictionary) -> Vector3:
	var goal = intention.get("goal", "")
	var desc = intention.get("description", "").to_lower()
	var search_names = []
	var memory_type = ""
	
	if goal == "eat" or "яг" in desc or "еда" in desc or "ед" in desc:
		search_names = ["food", "berry", "bush"]
		memory_type = "куст с ягодами"
	elif goal == "hide" or "укр" in desc or "пещер" in desc or "спрят" in desc:
		search_names = ["shelter", "cave"]
		memory_type = "укрытие"
	elif "вод" in desc or "рек" in desc or "пить" in desc or goal == "drink":
		search_names = ["water", "river"]
		memory_type = "вода"
	elif "дерев" in desc or "лес" in desc:
		search_names = ["tree"]
		memory_type = "дерево"
	elif "камен" in desc or "камн" in desc:
		search_names = ["rock", "stone"]
		memory_type = "камень"
	elif goal == "investigate" or goal == "explore":
		return _find_nearest_interesting_object()
	elif goal == "wander":
		return Vector3.ZERO
	
	if search_names.is_empty():
		return Vector3.ZERO
	
	var best_pos = _search_by_names(search_names)
	if best_pos == Vector3.ZERO and memory_type != "":
		best_pos = sensor_system.find_remembered_position(memory_type)
		if best_pos != Vector3.ZERO:
			print("🧠 Вспомнил где видел: ", memory_type)
	return best_pos

func _search_by_names(search_names: Array) -> Vector3:
	var best_dist = 999.0
	var best_pos = Vector3.ZERO
	for node in get_tree().get_nodes_in_group("interactable"):
		for sn in search_names:
			if sn in node.name.to_lower():
				var dist = agent.global_position.distance_to(node.global_position)
				if dist < best_dist:
					best_dist = dist
					best_pos = node.global_position
	if best_pos == Vector3.ZERO:
		best_pos = _search_scene_tree(get_tree().root, search_names)
	return best_pos

func _search_scene_tree(node: Node, search_names: Array) -> Vector3:
	var best_pos = Vector3.ZERO
	var best_dist = 999.0
	for child in node.get_children():
		if child is Node3D:
			for sn in search_names:
				if sn in child.name.to_lower():
					var dist = agent.global_position.distance_to(child.global_position)
					if dist < best_dist:
						best_dist = dist
						best_pos = child.global_position
		var found = _search_scene_tree(child, search_names)
		if found != Vector3.ZERO:
			var dist = agent.global_position.distance_to(found)
			if dist < best_dist:
				best_dist = dist
				best_pos = found
	return best_pos

func _find_nearest_interesting_object() -> Vector3:
	var perception = sensor_system.get_visual_perception()
	var best_dist = 999.0
	var best_pos = Vector3.ZERO
	for item in perception:
		var obj = item["object"]
		if obj == "ничего" or obj == "земля" or obj == "дерево":
			continue
		if item["distance"] < best_dist:
			best_dist = item["distance"]
			var angle = _label_to_angle(item["direction"])
			var dir = agent.global_transform.basis * Vector3(sin(deg_to_rad(angle)), 0, -cos(deg_to_rad(angle)))
			best_pos = agent.global_position + dir * item["distance"]
	return best_pos

func _label_to_angle(label: String) -> float:
	match label:
		"слева сзади": return -90.0
		"далеко слева": return -60.0
		"слева": return -30.0
		"чуть левее": return -15.0
		"впереди": return 0.0
		"чуть правее": return 15.0
		"справа": return 30.0
		"далеко справа": return 60.0
		"справа сзади": return 90.0
	return 0.0

func _on_navigation_finished():
	has_goal = false
	goal_just_reached = true
	agent.velocity.x = 0
	agent.velocity.z = 0
	print("✅ Дошёл до цели: ", current_intention.get("description", "?"))
