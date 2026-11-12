## Headless check of the Godot SDK against a live gateway on 127.0.0.1:8080 backed by the mock nodes (the CI job
## starts them). Run: godot --headless --path sdk/godot --script res://test/run.gd   Exit code = number of failures.
extends SceneTree

const A = preload("res://addons/anansi/anansi.gd")
const URL := "http://127.0.0.1:8080"
var failures := 0
var passes := 0
var got: Array = []


func check(ok: bool, msg: String) -> void:
	print(("PASS " if ok else "FAIL ") + msg)
	if ok:
		passes += 1
	else:
		failures += 1


func make(key := "change-me", base := URL) -> Node:
	var c = A.new()
	root.add_child(c)
	c.setup(base, "demo", key, "dev:p1")
	c.fallback = func(_m): return "(local line)"
	return c


func _init() -> void:
	run.call_deferred()


func run() -> void:
	var msgs := [{"role": "user", "content": "hello"}]
	var world := {"npcs": [{"id": "brom", "name": "Brom", "role": "blacksmith"}],
			"locations": [{"id": "mill", "name": "Old Mill"}], "items": [{"id": "ore", "name": "Iron ore"}]}
	var c = make()
	var bad = make("WRONG")
	var r: Dictionary = await c.chat(msgs, "smith")
	check(r.source == "gateway" and r.say.ends_with("hello"), "gateway reply (%s)" % r.say)
	r = await bad.chat(msgs, "smith")
	check(r.source == "fallback" and r.say == "(local line)", "bad key falls back")

	var on_sentence := func(s): got.append(s)
	r = await c.chat_stream(msgs, on_sentence, "smith")
	check(r.source == "gateway" and got.size() >= 1 and "".join(got).ends_with("hello") and r.say == "".join(got), "stream delivers sentences")
	got.clear()
	r = await bad.chat_stream(msgs, on_sentence, "smith")
	check(r.source == "fallback" and got.size() == 1 and got[0] == "(local line)", "stream falls back once on bad key")

	var q: Dictionary = await c.quest(world, 2, "mining")
	check(q.source == "gateway" and q.quest.steps.size() >= 1 and q.quest.steps[0].target_id == "brom", "quest from gateway uses a world id")
	var arc: Dictionary = await c.storyline(world, 3)
	check(arc.source == "gateway" and arc.storyline.beats.size() >= 1, "storyline from gateway")
	q = await bad.quest(world, 2)
	check(q.source == "fallback" and q.quest == null, "quest with bad key: no quest")
	bad.quest_fallback = func(_w): return {"title": "Authored", "steps": []}
	q = await bad.quest(world, 2)
	check(q.source == "fallback" and q.quest.title == "Authored", "quest fallback supplies an authored quest")

	var down = make("change-me", "http://127.0.0.1:9")
	down.timeout_s = 1.0
	got.clear()
	r = await down.chat_stream(msgs, on_sentence)
	check(r.source == "fallback" and got.size() == 1, "stream with gateway unreachable falls back")
	var plain = A.new()
	root.add_child(plain)
	plain.setup("http://127.0.0.1:9", "demo", "x")
	plain.timeout_s = 1.0
	r = await plain.chat(msgs)
	check(r.source == "fallback" and r.say == "...", "default fallback line")
	print("%d passed, %d failed" % [passes, failures])
	quit(failures)
