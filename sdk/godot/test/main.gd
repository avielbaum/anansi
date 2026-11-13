## Main scene of the exported test game: runs the same checks as test/run.gd, then quits with the failure count.
extends Node


func _ready() -> void:
	var c = preload("res://test/checks.gd").new()
	add_child(c)
	get_tree().quit(await c.run())
