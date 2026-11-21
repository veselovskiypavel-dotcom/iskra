extends CharacterBody3D

@export var speed: float = 1.8

@onready var _nav: NavigationAgent3D = $NavigationAgent3D

var _pause_timer: float = 0.0
var _is_paused: bool = false
var _move_timer: float = 0.0

func _ready():
	_nav.target_desired_distance = 1.5
	_nav.avoidance_enabled = false
	_move_timer = randf_range(2.0, 8.0)

func _physics_process(delta):
	if not is_on_floor():
		velocity.y -= 9.8 * delta

	if _is_paused:
		_pause_timer -= delta
		velocity.x = 0
		velocity.z = 0
		if _pause_timer <= 0.0:
			_is_paused = false
			_pick_target()
		move_and_slide()
		return

	_move_timer -= delta
	if _move_timer <= 0.0 or _nav.is_navigation_finished():
		if randf() < 0.35:
			_is_paused = true
			_pause_timer = randf_range(4.0, 12.0)
			velocity.x = 0
			velocity.z = 0
			move_and_slide()
			return
		_pick_target()

	if not _nav.is_navigation_finished():
		var next = _nav.get_next_path_position()
		var dir = (next - global_position)
		dir.y = 0
		if dir.length() > 0.1:
			dir = dir.normalized()
			velocity.x = dir.x * speed
			velocity.z = dir.z * speed
			var look_target = global_position + dir
			look_target.y = global_position.y
			look_at(look_target)

	move_and_slide()

func _pick_target():
	var offset = Vector3(randf_range(-35.0, 35.0), 0, randf_range(-35.0, 35.0))
	var target = global_position + offset
	target.x = clamp(target.x, -90.0, 90.0)
	target.z = clamp(target.z, -115.0, 65.0)
	_nav.target_position = target
	_move_timer = randf_range(10.0, 25.0)
