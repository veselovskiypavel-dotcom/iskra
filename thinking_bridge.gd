extends HTTPRequest

var tick: int = 0
var is_thinking: bool = false

@onready var intention_system = $"../IntentionSystem"

func _ready():
	request_completed.connect(_on_response)
	var timer = Timer.new()
	add_child(timer)
	timer.wait_time = 3.0
	timer.one_shot = false
	timer.timeout.connect(_on_tick)
	timer.start()

func _on_tick():
	if is_thinking:
		return
	
	tick += 1
	is_thinking = true
	var snapshot = $"../SensorSystem".get_full_snapshot(tick, "день")
	var json = JSON.stringify(snapshot)
	var headers = ["Content-Type: application/json"]
	request("http://127.0.0.1:8000/think", headers, HTTPClient.METHOD_POST, json)

func _on_response(result, code, headers, body):
	is_thinking = false
	
	if code != 200:
		print("Ошибка: ", code)
		return
	
	var response = JSON.parse_string(body.get_string_from_utf8())
	print("💭 ", response.get("thought", "..."))
	print("😶 ", response.get("emotion", "..."))
	
	# Передать намерение в систему воли
	var intention = response.get("intention", {})
	if intention != null and intention is Dictionary:
		intention_system.set_intention(intention)
