extends CharacterBody3D

var speed: float = 3.0
var mouse_sensitivity: float = 0.003
var player_controlled: bool = false  # true = ты управляешь, false = ИИ

func _ready():
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED

func _input(event):
	# Переключение режима: Tab
	if event.is_action_pressed("ui_focus_next"):
		player_controlled = !player_controlled
		print("Режим: ", "ИГРОК" if player_controlled else "ИИ")
	
	if event.is_action_pressed("ui_cancel"):
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	
	# Камера — всегда работает (чтобы смотреть вокруг)
	if event is InputEventMouseMotion and player_controlled:
		rotate_y(-event.relative.x * mouse_sensitivity)
		$Camera3D.rotate_x(-event.relative.y * mouse_sensitivity)
		$Camera3D.rotation.x = clamp($Camera3D.rotation.x, -1.5, 1.5)

func _physics_process(delta):
	if player_controlled:
		_player_movement(delta)
	
	if not is_on_floor():
		velocity.y -= 9.8 * delta
	
	move_and_slide()

func _player_movement(delta):
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
