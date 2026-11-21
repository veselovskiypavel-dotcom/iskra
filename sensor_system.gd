extends Node3D

@onready var agent: CharacterBody3D = get_parent()

var view_distance: float = 50.0
var hearing_radius: float = 25.0

# ═══ ПРОСТРАНСТВЕННАЯ ПАМЯТЬ ═══
var spatial_memory: Dictionary = {}
var _memory_id_counter: int = 0
var memory_merge_distance: float = 5.0

# Важные объекты — приоритет в промпте
var _important_types: Array = ["вода", "куст с ягодами", "укрытие", "существо"]

func get_visual_perception() -> Array:
	var results = []
	var space_state = get_world_3d().direct_space_state
	var origin = agent.global_position + Vector3(0, 0.7, 0)
	
	var angles = [-90, -60, -30, -15, 0, 15, 30, 60, 90]
	var labels = ["слева сзади", "далеко слева", "слева", "чуть левее", "впереди", "чуть правее", "справа", "далеко справа", "справа сзади"]
	
	for i in range(angles.size()):
		var angle_rad = deg_to_rad(angles[i])
		var direction = agent.global_transform.basis * Vector3(sin(angle_rad), 0, -cos(angle_rad))
		
		var query = PhysicsRayQueryParameters3D.create(origin, origin + direction * view_distance)
		query.exclude = [agent.get_rid()]
		var hit = space_state.intersect_ray(query)
		
		if hit:
			var obj_name = _identify_object(hit.collider)
			var dist = origin.distance_to(hit.position)
			results.append({
				"direction": labels[i],
				"object": obj_name,
				"distance": snapped(dist, 0.1)
			})
			if obj_name != "земля" and obj_name != "что-то неизвестное":
				_remember_object(obj_name, hit.position)
		else:
			results.append({
				"direction": labels[i],
				"object": "ничего",
				"distance": view_distance
			})
	
	return results

func _remember_object(obj_type: String, world_pos: Vector3):
	for key in spatial_memory:
		var mem = spatial_memory[key]
		if mem["type"] == obj_type:
			if mem["position"].distance_to(world_pos) < memory_merge_distance:
				mem["position"] = world_pos
				mem["times_seen"] += 1
				return
	
	_memory_id_counter += 1
	var key = "%s_%d" % [obj_type, _memory_id_counter]
	spatial_memory[key] = {
		"type": obj_type,
		"position": world_pos,
		"times_seen": 1
	}

func get_spatial_memory_description() -> String:
	if spatial_memory.is_empty():
		return "  (ничего не помню)"
	
	var origin = agent.global_position
	
	# Разделяем на важные и обычные
	var important = []
	var ordinary = []
	
	for key in spatial_memory:
		var mem = spatial_memory[key]
		var dist = origin.distance_to(mem["position"])
		var entry = {"mem": mem, "dist": dist}
		if mem["type"] in _important_types:
			important.append(entry)
		else:
			ordinary.append(entry)
	
	important.sort_custom(func(a, b): return a["dist"] < b["dist"])
	ordinary.sort_custom(func(a, b): return a["dist"] < b["dist"])
	
	var lines = []
	
	# Все важные (до 5)
	for entry in important.slice(0, 5):
		var mem = entry["mem"]
		var dist = snapped(entry["dist"], 0.5)
		var dir = _get_cardinal_direction(mem["position"])
		lines.append("  ★ %s — %s, ~%.0fм" % [mem["type"], dir, dist])
	
	# Ближайшие обычные (до 3)
	for entry in ordinary.slice(0, 3):
		var mem = entry["mem"]
		var dist = snapped(entry["dist"], 0.5)
		var dir = _get_cardinal_direction(mem["position"])
		lines.append("  %s — %s, ~%.0fм" % [mem["type"], dir, dist])
	
	if lines.is_empty():
		return "  (ничего не помню)"
	
	return "\n".join(lines)

func find_remembered_position(obj_type: String) -> Vector3:
	var best_dist = 999.0
	var best_pos = Vector3.ZERO
	
	for key in spatial_memory:
		var mem = spatial_memory[key]
		if mem["type"] == obj_type:
			var dist = agent.global_position.distance_to(mem["position"])
			if dist < best_dist:
				best_dist = dist
				best_pos = mem["position"]
	
	return best_pos

func get_audio_perception() -> Array:
	var results = []
	var origin = agent.global_position
	
	for node in get_tree().get_nodes_in_group("sound_source"):
		var dist = origin.distance_to(node.global_position)
		if dist <= hearing_radius:
			var dir = _get_relative_direction(node.global_position)
			results.append({
				"sound": node.get_meta("sound_type", "неизвестный звук"),
				"direction": dir,
				"distance": _classify_distance(dist)
			})
	
	return results

func get_touch_perception() -> Dictionary:
	return {
		"ground": "трава",
		"temperature": "тепло",
		"wind": "тихо"
	}

func get_full_snapshot(tick: int, world_time: String) -> Dictionary:
	return {
		"tick": tick,
		"world_time": world_time,
		"vision": get_visual_perception(),
		"hearing": get_audio_perception(),
		"touch": get_touch_perception(),
		"internal_state": $"../InternalState".get_description(),
		"known_places": get_spatial_memory_description()
	}

func _identify_object(collider: Node) -> String:
	var node = collider
	for _i in range(4):
		if node == null:
			break
		var cname = node.name.to_lower()
		
		if "tree" in cname:
			return "дерево"
		elif "rock" in cname or "stone" in cname or "boulder" in cname:
			return "камень"
		elif "food" in cname or "berry" in cname or "bush" in cname or "mushroom" in cname:
			return "куст с ягодами"
		elif "water" in cname or "river" in cname or "lake" in cname or "pond" in cname:
			return "вода"
		elif "shelter" in cname or "cave" in cname:
			return "укрытие"
		elif "ground" in cname or "terrain" in cname or "floor" in cname:
			return "земля"
		elif "creature" in cname or "animal" in cname:
			return "существо"
		elif "wall" in cname or "fence" in cname:
			return "стена"
		elif "hill" in cname or "mountain" in cname:
			return "холм"
		elif "grass" in cname or "plant" in cname or "flower" in cname:
			return "растение"
		
		node = node.get_parent()
	
	if collider.has_meta("object_type"):
		return collider.get_meta("object_type")
	
	return "что-то неизвестное"

func _get_cardinal_direction(target_pos: Vector3) -> String:
	"""Стороны света — стабильные, не зависят от поворота агента."""
	var delta = target_pos - agent.global_position
	# В Godot: +X = восток, -X = запад, +Z = юг, -Z = север
	var ns = ""
	var ew = ""
	
	if delta.z < -2.0:
		ns = "север"
	elif delta.z > 2.0:
		ns = "юг"
	
	if delta.x > 2.0:
		ew = "восток"
	elif delta.x < -2.0:
		ew = "запад"
	
	if ns != "" and ew != "":
		return "на %s-%s" % [ns + "о", ew + "е"]
	elif ns != "":
		return "на %s" % [ns + "е"]
	elif ew != "":
		return "на %s" % [ew + "е"]
	else:
		return "рядом"

func _get_relative_direction(target_pos: Vector3) -> String:
	var to_target = (target_pos - agent.global_position).normalized()
	var forward = -agent.global_transform.basis.z
	var right = agent.global_transform.basis.x
	
	var dot_forward = forward.dot(to_target)
	var dot_right = right.dot(to_target)
	
	var result = ""
	if dot_forward > 0.5:
		result = "впереди"
	elif dot_forward < -0.5:
		result = "сзади"
	
	if dot_right > 0.3:
		result += "-справа" if result else "справа"
	elif dot_right < -0.3:
		result += "-слева" if result else "слева"
	
	return result if result else "рядом"

func _classify_distance(dist: float) -> String:
	if dist < 5:
		return "близко"
	elif dist < 15:
		return "средне"
	else:
		return "далеко"
