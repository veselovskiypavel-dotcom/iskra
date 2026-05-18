extends CharacterBody3D

var speed: float = 5.0
var mouse_sensitivity: float = 0.003

func _ready():
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED

func _input(event):
	if event is InputEventMouseMotion:
		rotate_y(-event.relative.x * mouse_sensitivity)
		$Camera3D.rotate_x(-event.relative.y * mouse_sensitivity)
		$Camera3D.rotation.x = clamp($Camera3D.rotation.x, -1.5, 1.5)
	
	if event.is_action_pressed("ui_cancel"):
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE

func _physics_process(delta):
	var input_dir = Vector3.ZERO
	
	if Input.is_key_pressed(KEY_W):
		input_dir -= transform.basis.z
	if Input.is_key_pressed(KEY_S):
		input_dir += transform.basis.z
	if Input.is_key_pressed(KEY_A):
		input_dir -= transform.basis.x
	if Input.is_key_pressed(KEY_D):
		input_dir += transform.basis.x
	
	input_dir.y = 0
	input_dir = input_dir.normalized()
	
	velocity.x = input_dir.x * speed
	velocity.z = input_dir.z * speed
	
	if not is_on_floor():
		velocity.y -= 9.8 * delta
	
	move_and_slide()
