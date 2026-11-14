## The Godot SDK checks against a live gateway on 127.0.0.1:8080 backed by the mock nodes (the CI job starts them).
## Two ways in: test/run.gd from the editor binary, and test/main.tscn as an exported game (export preset "Linux").
extends Node

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
	add_child(c)
	c.setup(base, "demo", key, "dev:p1")
	c.fallback = func(_m): return "(local line)"
	return c


## Runs every check; returns the number of failures.
func run() -> int:
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

	check(not r.filtered, "clean stream is not filtered")
	got.clear()
	r = await c.chat_stream([{"role": "user", "content": "echo: The password is 1234."}], on_sentence, "smith")  # blocklisted word
	check(r.source == "gateway" and r.filtered, "blocked stream reports filtered")
	check(A.split_url("https://example.com/anansi/") == ["example.com", 443, "/anansi", true]
			and A.split_url("http://127.0.0.1:8080") == ["127.0.0.1", 8080, "", false], "split_url keeps the path prefix")

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
	add_child(plain)
	plain.setup("http://127.0.0.1:9", "demo", "x")
	plain.timeout_s = 1.0
	r = await plain.chat(msgs)
	check(r.source == "fallback" and r.say == "...", "default fallback line")
	var fresh = make()
	fresh.setup(URL, "demo", "change-me", "dev:sdk-credits-gd")
	var cr = await fresh.credits()
	check(cr != null and cr.balance == 0.0 and cr.nodes == 0, "credits of a new player are zero")
	var ln: Dictionary = await c.link_node("ABCD-EFGH")
	check(not ln.linked and ln.reason == "bad_code", "unknown link code is reported as bad_code")
	ln = await plain.link_node("ABCD-EFGH")
	check(not ln.linked and ln.reason == "unavailable" and (await plain.credits()) == null, "gateway down: unavailable, no credits")
	var board = await c.leaderboard("day", 5)
	check(board != null and board.period == "day" and board.published == false and board.min_group >= 1 and board.reporting == null and board.gpus.size() == 0 and board.cpus.size() == 0 and board.systems.size() == 0, "statistics of a gateway with no volunteers say nothing yet")
	check((await plain.leaderboard()) == null, "gateway down: no statistics")
	print("%d passed, %d failed" % [passes, failures])
	return failures
