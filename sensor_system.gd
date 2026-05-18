extends Node3D

@onready var agent: CharacterBody3D = get_parent()

var view_distance: float = 20.0
var hearing_radius: float = 25.0

func get_visual_perception() -> Array:
	var results = []
	var space_state = get_world_3d().direct_space_state
	var origin = agent.global_position + Vector3(0, 0.7, 0)  # уровень глаз
	
	# 7 лучей веером
	var angles = [-60, -30, -15, 0, 15, 30, 60]
	var labels = ["далеко слева", "слева", "чуть левее", "впереди", "чуть правее", "справа", "далеко справа"]
	
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
		else:
			results.append({
				"direction": labels[i],
				"object": "ничего",
				"distance": view_distance
			})
	
	return results

func get_audio_perception() -> Array:
	var results = []
	var origin = agent.global_position
	
	# Ищем все Area3D в радиусе слышимости
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
		"internal_state": $"../InternalState".get_description()
	}

func _identify_object(collider: Node) -> String:
	var name = collider.name.to_lower()
	
	if "tree" in name:
		return "дерево"
	elif "rock" in name or "stone" in name:
		return "камень"
	elif "food" in name or "berry" in name or "bush" in name:
		return "куст с ягодами"
	elif "water" in name or "river" in name:
		return "вода"
	elif "shelter" in name or "cave" in name:
		return "укрытие"
	elif "ground" in name:
		return "земля"
	elif "creature" in name:
		return "существо"
	else:
		return collider.name

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
