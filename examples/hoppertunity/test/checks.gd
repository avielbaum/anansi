## Self-checks for the sim and the crew layer. Prints "<n> failed" last.
## The HTTP checks pass with or without a gateway: with one they exercise the live path, without one the fallback path.
## HOP_GATEWAY sets its address (default http://127.0.0.1:8080); HOP_REQUIRE_LIVE=1 (CI) fails the run if it did not answer.
## The gateway must serve the "hoppertunity" title on mock nodes (tools/mock_node.py), which echo a scripted reply.
extends Node

var failed := 0


func ok(cond: bool, what: String) -> void:
	if not cond:
		failed += 1
	print("ok   " if cond else "FAIL ", what)


## A sim with a row of buildings starting at (0, 0) and running east.
func line(kinds: Array, money := 100000) -> Sim:
	var s := Sim.new()
	s.money = money
	s.unlocked = Data.BUILD.keys() + Data.ITEMS.keys()
	for i in kinds.size():
		s.build(kinds[i], Vector2i(i, 0), 0)
	return s


func run_ticks(s: Sim, n: int) -> void:
	for i in n:
		s.step()


func items_on(s: Sim) -> int:
	return s.cells.values().filter(func(c): return c.get("item", "") != "").size()


func run() -> int:
	# --- flow ---
	var s := line(["inbound", "belt", "belt", "belt", "outbound"])
	run_ticks(s, 60)
	ok(s.today.shipped > 5, "crates travel dock -> belts -> dock (%d shipped)" % s.today.shipped)
	ok(s.today.revenue == s.today.shipped * 1, "raw steel sells for 1 each at morale 50")

	s = line(["inbound", "belt", "belt", "belt"])
	run_ticks(s, 100)
	ok(items_on(s) == 3, "a blocked line fills up and loses nothing")
	var spent: int = 100000 - s.money - 100 - 15
	ok(spent == 3 * 2, "the dock only charges for crates it could unload")

	# --- machines ---
	s = line(["inbound", "press", "belt", "outbound"])
	run_ticks(s, 120)
	ok(s.contract.done > 5, "press turns steel into panels, and panels count for the contract (%d)" % s.contract.done)

	s = Sim.new()
	s.money = 100000
	s.unlocked = Data.BUILD.keys() + Data.ITEMS.keys()
	s.build("inbound", Vector2i(0, 0), 0)
	s.build("press", Vector2i(1, 0), 0)
	s.build("assembler", Vector2i(2, 0), 0)
	s.build("outbound", Vector2i(3, 0), 0)
	s.build("inbound", Vector2i(2, 2), 3)
	s.cycle_raw(Vector2i(2, 2))
	s.build("molder", Vector2i(2, 1), 3)
	var got := {}
	s.sold.connect(func(_p, item, _a): got[item] = got.get(item, 0) + 1)
	run_ticks(s, 200)
	ok(got.get("gadget", 0) > 3 and got.size() == 1, "assembler joins panels and casings into gadgets %s" % got)

	s = line(["inbound", "splitter", "belt", "outbound"])
	s.build("belt", Vector2i(1, 1), 1)
	s.build("hopper", Vector2i(1, 2), 1)
	run_ticks(s, 100)
	var a: int = s.today.shipped
	var b: int = s.cells[Vector2i(1, 2)].store.size()
	ok(absi(a - b) <= 2 and a > 3, "splitter shares crates between its outputs (%d ahead, %d right)" % [a, b])

	s = line(["inbound", "hopper"])
	run_ticks(s, 400)
	ok(s.cells[Vector2i(1, 0)].store.size() == Data.HOPPER_CAP, "a hopper with no way out fills to its cap and stops the dock")

	# --- morale ---
	var out := []
	for m in [0.0, 100.0]:
		s = line(["inbound", "press", "outbound"])
		s.morale.tech = m
		s.morale.qa = 100.0
		run_ticks(s, 200)
		out.append(s.today.shipped)
	ok(out[1] > out[0], "a happy technician's press makes more (%d vs %d)" % [out[1], out[0]])

	s = Sim.new()
	for i in 5:
		s.apply_action("tech", "morale_up")
	ok(s.morale.tech == 60.0, "talk moves morale at most %d a day" % Data.MORALE_DAILY_CAP)
	ok(s.apply_action("tech", "launch_rocket") == "" and s.morale.tech == 60.0, "an unknown action does nothing")
	ok(s.apply_action("sales", "share_tip").contains("casings"), "a tip reveals the next contract")
	s.answer_raise("dock", true)
	ok(s.wages.dock == 20 and s.morale.dock == 65.0, "a raise costs wages and lifts morale")

	s = line(["inbound", "press", "outbound"])
	s.morale.qa = 0.0
	run_ticks(s, 200)
	ok(s.today.defects > 0, "an unhappy quality lead means returned units (%d)" % s.today.defects)

	s = Sim.new()
	for id in s.morale:
		s.morale[id] = 10.0
	run_ticks(s, Data.TICKS_PER_DAY)
	ok(s.walkout and s.day == 2, "a miserable crew walks out the next day")
	s.build("inbound", Vector2i(0, 0), 0)
	s.build("belt", Vector2i(1, 0), 0)
	run_ticks(s, 30)
	ok(items_on(s) == 0, "nothing moves during a walkout")

	# --- contracts and money ---
	s = line(["inbound", "press", "outbound"], 1000)
	s.unlocked = Data.START_UNLOCKS.duplicate()
	s.morale.qa = 100.0
	s.contract.qty = 3
	run_ticks(s, 100)
	ok(s.contracts_done == 1 and "molder" in s.unlocked and s.contract.item == "casing", "finishing a contract unlocks the next machine")

	s = Sim.new()
	var m0 := s.money
	run_ticks(s, Data.TICKS_PER_DAY * 2)
	ok(s.money == m0 - 2 * (Data.RENT + 60) - 50 and s.contract.due == 4, "a missed contract costs a penalty and is offered again")
	s.money = Data.BANKRUPT_AT - 1
	ok(s.bankrupt(), "deep enough in debt is bankruptcy")

	# --- quests and stories ---
	var all_start := true
	for id in Data.QUESTS:
		for q in Data.QUESTS[id]:
			all_start = all_start and Sim.new().start_quest(q, id)
	ok(all_start, "every authored quest only names things the game has")
	s = Sim.new()
	ok(not s.start_quest({"title": "x", "reward_tier": "small", "steps": [{"objective": "talk_to", "target_id": "nobody"}]}, "dock"),
			"a quest that names something unknown is refused")
	s.start_quest(Data.QUESTS.tech[0], "tech")
	m0 = s.money
	s.quest_event("talk_to", "tech")  # out of order: ignored
	s.quest_event("inspect", "press")
	s.quest_event("talk_to", "tech")
	ok(s.quest.is_empty() and s.money == m0 + 60 and s.morale.tech == 55.0 and s.quests_done.tech == 1, "a finished quest pays its tier")

	s = Sim.new()
	ok(s.next_beat("qa") == 0, "the first story beat is ready at once")
	s.tell_beat("qa")
	ok(s.next_beat("qa") == -1, "the next beat waits for a finished quest")
	s.quests_done.qa = 3
	for i in 3:
		s.tell_beat("qa")
	ok(s.perks.has("qa"), "a finished storyline gives its perk")

	# --- saving ---
	s = line(["inbound", "splitter", "press", "belt", "outbound"])
	s.build("hopper", Vector2i(1, 1), 1)
	s.start_quest(Data.QUESTS.dock[0], "dock")
	run_ticks(s, 150)
	var t := Sim.new()
	t.restore(JSON.parse_string(JSON.stringify(s.save())))
	t.rng.state = s.rng.state
	run_ticks(s, 400)
	run_ticks(t, 400)
	ok(t.money == s.money and t.day == s.day and JSON.stringify(t.save()) == JSON.stringify(s.save()), "a saved game continues exactly as the original")

	# --- crew: what an answer may do (a scripted Anansi, so every action is exercised) ---
	s = Sim.new()
	var crew := Crew.new()
	var fake := Scripted.new()
	crew.api = fake
	add_child(crew)
	crew.setup(s, "http://127.0.0.1:1", "hoppertunity", "x", "ci")
	fake.next = "morale_up"
	var r: Dictionary = await crew.talk("tech", "Good work on the press today.")
	ok(s.morale.tech == 55.0 and r.note != "", "a kind word the model rewards lifts morale")
	fake.next = "fire_everyone"
	r = await crew.talk("tech", "hello")
	ok(r.note == "" and s.morale.tech == 55.0 and s.money == Data.START_MONEY, "an action outside the whitelist is dropped")
	fake.next = "ask_raise"
	r = await crew.talk("tech", "How is the pay?")
	ok(r.raise and s.wages.tech == 15, "a raise is the player's decision, not the model's")
	fake.next = "offer_quest"
	r = await crew.talk("tech", "Anything I can do?")
	ok(r.note.begins_with("New quest") and s.quest.giver == "tech", "offer_quest starts that coworker's quest")
	ok(crew.history.tech.size() == 6 and fake.seen[0].role == "system" and "Sprocket" in fake.seen[0].content,
			"the coworker gets a brief of who they are, and the last three exchanges")

	# --- crew over HTTP: with a gateway on 127.0.0.1:8080 the live path, without one the fallback ---
	s = Sim.new()
	crew = Crew.new()
	add_child(crew)
	var url := OS.get_environment("HOP_GATEWAY") if OS.has_environment("HOP_GATEWAY") else "http://127.0.0.1:8080"
	var live := OS.get_environment("HOP_REQUIRE_LIVE") == "1"
	crew.setup(s, url, "hoppertunity", "change-me", "ci")
	crew.api.timeout_s = 5.0
	r = await crew.talk("tech", 'echo: {"say": "Bertha is purring, boss.", "action": "morale_up"}')
	print("     chat source: ", r.source)
	ok(r.say != "" and (r.source == "gateway" or not live), "a coworker always answers (%s)" % r.say)
	ok(s.morale.tech == 50.0, "typing an action's name does not trigger it")

	crew.api.generation_timeout_s = 10.0
	await crew.refill()
	print("     quests generated by the gateway: ", crew.queued.size())
	ok(crew.queued.size() == 4 or not live, "the gateway generates a quest for every coworker")
	var note := crew.offer_quest("dock")
	ok(note.begins_with("New quest") and not s.quest.is_empty() and s.quest.giver == "dock", "a coworker hands out a quest, generated or authored (%s)" % s.quest.title)
	ok(crew.offer_quest("tech").begins_with("Finish"), "one quest at a time")
	ok(crew.story_beat("dock") != "" and crew.story_beat("dock") == "", "a coworker tells one story beat, then waits")

	print("%d failed" % failed)
	return failed


## Stands in for the gateway: answers every chat with the action in `next`.
class Scripted:
	extends Anansi
	var next := "none"
	var seen := []

	func chat(messages: Array, _npc_id := "", _structured := false) -> Dictionary:
		seen = messages
		return {"source": "gateway", "say": "Right you are, boss.", "action": next, "filtered": false}

	func quest(_w: Dictionary, _s := 3, _t := "", _d := "normal", _so := "", _p := "") -> Dictionary:
		return {"source": "fallback", "quest": null}

	func storyline(_w: Dictionary, _b := 4, _t := "") -> Dictionary:
		return {"source": "fallback", "storyline": null}
