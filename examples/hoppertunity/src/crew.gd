## The coworkers' voices: every Anansi call the game makes, and what each answer is allowed to do to the sim.
## The model chooses words and one whitelisted action; sim.gd owns every number. With no gateway, the lines, quests and
## stories in data.gd are used instead and the game plays the same.
class_name Crew
extends Node

var sim: Sim
var api := Anansi.new()
var online := false  # did the last chat come from the gateway?
var history := {}  # crew id -> the last few messages, so a coworker remembers the conversation
var queued := {}  # crew id -> a quest generated ahead of time
var stories := {}  # crew id -> four beats (generated at the start of a game, else Data.STORIES)
var _filling := false


func setup(s: Sim, url: String, title: String, key: String, player_id: String) -> void:
	sim = s
	add_child(api)
	api.setup(url, title, key, "dev:" + player_id)
	api.timeout_s = 20.0  # a small local model on CPU needs longer than the SDK's 3 s default
	for id in Data.CREW:
		history[id] = []
		if not stories.has(id):
			stories[id] = Data.STORIES[id]


## Say `text` to a coworker. Returns {"say", "source", "note", "raise"}: note is what changed in the game ("" if
## nothing), raise is true when they asked for one and the player must answer (sim.answer_raise).
func talk(id: String, text: String) -> Dictionary:
	sim.quest_event("talk_to", id)
	var msgs: Array = [{"role": "system", "content": _brief(id)}] + history[id] + [{"role": "user", "content": text}]
	api.fallback = func(_m): return line(id)
	var r: Dictionary = await api.chat(msgs, id, true)
	online = r.source == "gateway"
	history[id] = (history[id] + [{"role": "user", "content": text}, {"role": "assistant", "content": r.say}]).slice(-6)
	var out := {"say": r.say, "source": r.source, "note": "", "raise": false}
	var action: String = r.action if r.action in Data.ACTIONS else "none"
	if action == "offer_quest":
		out.note = offer_quest(id)
	elif action == "ask_raise":
		out.raise = true
	else:
		out.note = sim.apply_action(id, action)
	return out


## An authored line for this coworker's current mood.
func line(id: String) -> String:
	var pool: Array = Data.LINES[id][sim.mood(id)]
	return pool[sim.rng.randi() % pool.size()]


## Hand the player this coworker's next quest: the generated one if it is queued and valid, else an authored one.
func offer_quest(id: String) -> String:
	if not sim.quest.is_empty():
		return "Finish \"%s\" first." % sim.quest.title
	var q = queued.get(id)
	queued.erase(id)
	if q == null or not sim.start_quest(q, id):
		var pool: Array = Data.QUESTS[id]
		sim.start_quest(pool[sim.quests_done[id] % pool.size()], id)
	refill()
	return "New quest: %s" % sim.quest.title


## The next storyline beat this coworker tells, or "" if they have nothing new to say yet.
func story_beat(id: String) -> String:
	var n := sim.next_beat(id)
	if n < 0:
		return ""
	sim.tell_beat(id)
	var text: String = stories[id][n]
	if sim.perks.has(id):
		text += "\n[%s]" % Data.CREW[id].perk
	return text


## Generate ahead of time, one request at a time: a quest for every coworker who has none queued, and at the start of
## a game each coworker's storyline. Generation takes tens of seconds, so it never happens while the player waits.
func refill() -> void:
	if _filling:
		return
	_filling = true
	for id in Data.CREW:
		if not queued.has(id):
			var r: Dictionary = await api.quest(_world(), 3, Data.CREW[id].role, "normal", _story_so_far(id), Data.PLAYER)
			if r.quest != null:
				queued[id] = r.quest
		if sim.beats_told[id] == 0 and stories[id] == Data.STORIES[id]:
			var one := {"npcs": [_npc(id)], "locations": _world().locations, "items": []}
			var s: Dictionary = await api.storyline(one, 4, Data.CREW[id].persona)
			if s.storyline != null and s.storyline.get("beats") is Array and s.storyline.beats.size() >= 4:
				stories[id] = s.storyline.beats.slice(0, 4).map(func(b): return str(b.get("summary", "")))
	_filling = false


## Everything a quest may refer to: the coworkers, the stations and goods unlocked so far.
func _world() -> Dictionary:
	var w := {"npcs": [], "locations": [], "items": []}
	for id in Data.CREW:
		w.npcs.append(_npc(id))
	for u in sim.unlocked:
		if Data.BUILD.has(u):
			w.locations.append({"id": u, "name": Data.BUILD[u].place})
		elif Data.ITEMS[u].sell > 0:
			w.items.append({"id": u, "name": Data.ITEMS[u].name})
	return w


func _npc(id: String) -> Dictionary:
	return {"id": id, "name": Data.CREW[id].name, "role": Data.CREW[id].role}


func _story_so_far(id: String) -> String:
	return " ".join(stories[id].slice(0, sim.beats_told[id]))


## Who the coworker is and how the factory is doing, so what they say fits the game. The rules for choosing an action
## are in the title's system_prefix (config.hoppertunity.json).
func _brief(id: String) -> String:
	var c: Dictionary = Data.CREW[id]
	var k: Dictionary = sim.contract
	return ("You are %s, the %s at the Hopper Works. %s You are talking to %s. Your morale is %d out of 100 (%s). "
			+ "It is day %d. The plant has %d coins. Current contract: %d %s due by the end of day %d, %d shipped so far. %s") % [
			c.name, c.role, c.persona, Data.PLAYER, int(sim.morale[id]), sim.mood(id), sim.day, sim.money,
			k.qty, Data.ITEMS[k.item].name, k.due, k.done, _story_so_far(id)]
