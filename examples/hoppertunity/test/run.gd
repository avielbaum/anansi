## Headless self-check. Run: godot --headless --path examples/hoppertunity --script res://test/run.gd
## Exit code = number of failures; the log ends with "<n> failed".
extends SceneTree


func _init() -> void:
	go.call_deferred()


func go() -> void:
	var c = preload("res://test/checks.gd").new()
	root.add_child(c)
	quit(await c.run())
