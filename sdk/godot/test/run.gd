## Headless check of the Godot SDK from the editor binary. Run: godot --headless --path sdk/godot --script res://test/run.gd
## Exit code = number of failures. The checks themselves are in checks.gd (shared with the exported-game test, main.tscn).
extends SceneTree


func _init() -> void:
	go.call_deferred()


func go() -> void:
	var c = preload("res://test/checks.gd").new()
	root.add_child(c)
	quit(await c.run())
