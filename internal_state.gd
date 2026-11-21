extends Node

var energy: float = 0.8
var thirst: float = 0.9
var safety: float = 1.0
var curiosity: float = 0.3
var comfort: float = 0.7

var energy_decay: float = 0.0005
var thirst_decay: float = 0.001

var time_without_stimuli: float = 0.0
var time_stationary: float = 0.0
var _last_pos: Vector3 = Vector3.ZERO

func _process(delta):
	energy = max(0.0, energy - energy_decay * delta)
	thirst = max(0.0, thirst - thirst_decay * delta)
	
	time_without_stimuli += delta
	if time_without_stimuli > 10.0:
		curiosity = min(1.0, curiosity + 0.03 * delta)
	
	var parent = get_parent()
	if parent is CharacterBody3D:
		var current_pos = parent.global_position
		if current_pos.distance_to(_last_pos) < 0.3:
			time_stationary += delta
			if time_stationary > 20.0:
				curiosity = min(1.0, curiosity + 0.05 * delta)
		else:
			time_stationary = 0.0
		_last_pos = current_pos
	
	if int(time_without_stimuli) % 10 == 0 and fmod(time_without_stimuli, 10.0) < delta:
		print("Энергия: %.2f  Жажда: %.2f  Любопытство: %.2f  Неподвижность: %.0fс" % [energy, thirst, curiosity, time_stationary])

func feed(amount: float):
	energy = min(1.0, energy + amount)

func drink(amount: float):
	thirst = min(1.0, thirst + amount)

func register_stimulus():
	time_without_stimuli = 0.0
	curiosity = max(0.0, curiosity - 0.1)

func get_description() -> Dictionary:
	return {
		"energy": _describe(energy, "сыт", "голоден", "истощён"),
		"thirst": _describe(thirst, "напился", "хочет пить", "сильная жажда"),
		"safety": _describe(safety, "в безопасности", "тревожно", "опасно"),
		"curiosity": _describe(curiosity, "спокоен", "любопытно", "очень скучно"),
		"energy_value": energy,
		"thirst_value": thirst,
		"safety_value": safety,
		"curiosity_value": curiosity
	}

func _describe(value: float, good: String, mid: String, bad: String) -> String:
	if value > 0.6:
		return good
	elif value > 0.3:
		return mid
	else:
		return bad
