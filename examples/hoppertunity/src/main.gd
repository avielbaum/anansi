## The game you see: draws the Sim, takes the mouse and keyboard, and shows the crew's conversations.
## Everything is built in code so the scene file stays one node. Rules live in sim.gd, words in crew.gd.
extends Node3D

const GATEWAY := "http://127.0.0.1:8080"  # the local Anansi gateway (see README); the game plays without it
const SAVE := "user://hoppertunity.json"
const TICK := 0.25
const MODELS := "res://assets/models/"
const PEOPLE := "res://assets/characters/"
## model, scale, tint and arrow height of each building. The kit's pieces face +Z, so YAW0 turns them to face direction 0 (+X).
const YAW0 := PI / 2
const LOOK := {
	"belt": ["conveyor-stripe", 1.0, Color.WHITE, 0.42], "splitter": ["conveyor-stripe", 1.0, Color(1.0, 0.75, 0.35), 0.42],
	"hopper": ["hopper-square", 0.85, Color.WHITE, 0.9],
	"inbound": ["structure-doorway-wide", 0.5, Color(0.75, 1.0, 0.8), 1.53], "outbound": ["structure-doorway-wide", 0.5, Color(1.0, 0.8, 0.6), 1.53],
	"press": ["machine", 0.75, Color.WHITE, 1.0], "molder": ["machine-window", 0.75, Color(0.75, 0.95, 1.0), 1.0],
	"assembler": ["machine-fortified", 0.72, Color(1.0, 0.9, 0.75), 1.0], "packer": ["robot-arm-a", 0.42, Color.WHITE, 0.03],
}
const ITEM_LOOK := {
	"steel": ["box-small", 0.55, Color(0.62, 0.66, 0.78)], "plastic": ["box-small", 0.55, Color(0.45, 0.9, 1.0)],
	"cardboard": ["box-wide", 0.5, Color.WHITE], "panel": ["cog-a", 0.5, Color(0.8, 0.84, 0.95)],
	"casing": ["cog-a", 0.5, Color(0.45, 0.9, 1.0)], "gadget": ["button-floor-round", 1.0, Color.WHITE],
	"boxed": ["box-large", 0.5, Color.WHITE],
}
const CREW_LOOK := {"dock": "character-worker", "tech": "character-male-c", "qa": "character-female-e", "sales": "character-female-b"}
const HELP := "Click a build button, then the floor. R turns the piece, right-click cancels or removes. Click a coworker to talk, a building to inspect it, an inbound dock to change what it orders. WASD or arrows move, Q and E turn the view, the wheel zooms, Space pauses."
const INK := Color("2b2a3a")
const ORANGE := Color("f2a13c")

var sim: Sim
var crew: Crew
var player_id := ""
var speed := 1.0
var acc := 0.0
var tool := ""  # the building being placed, "" for none
var tool_dir := 0
var talking := ""  # the coworker in the talk panel
var modal := false  # the day-end screen is up: time stands still

var cam := Camera3D.new()
var pivot := Vector3(8, 0, 6)
var yaw := 0
var zoom := 16.0
var views := {}  # Vector2i -> the building's Node3D
var item_mm := {}  # item id -> MultiMesh
var floor_mm := MultiMesh.new()
var ghost := Node3D.new()
var ghost_key := ""
var crew_nodes := {}  # crew id (and "pip") -> Node3D
var pip_goal := Vector3.ZERO  # where Pip is walking to

var top: Label
var contract_label: Label
var quest_label: Label
var day_bar: ProgressBar
var build_bar: HBoxContainer
var toast: Label
var talk_panel: PanelContainer
var talk_log: RichTextLabel
var talk_title: Label
var talk_input: LineEdit
var raise_row: HBoxContainer
var day_panel: PanelContainer
var day_text: RichTextLabel
var net_label: Label


func _ready() -> void:
	_world()
	_ui()
	_start(_load())


# ---------- a game begins ----------

func _start(saved: Dictionary) -> void:
	sim = Sim.new(randi())
	if crew != null:
		crew.queue_free()
	crew = Crew.new()
	if saved.is_empty():
		player_id = "pip-%08x" % (randi() & 0x7fffffff)
	else:
		sim.restore(saved.sim)
		crew.stories = saved.stories
		player_id = saved.player
	add_child(crew)
	crew.setup(sim, GATEWAY, "hoppertunity", "change-me", player_id)
	sim.sold.connect(_on_sold)
	sim.day_ended.connect(_on_day_end)
	sim.contract_changed.connect(_on_contract)
	sim.quest_changed.connect(_on_quest)
	for v in views.values():
		v.queue_free()
	views = {}
	for pos in sim.cells:
		_refresh(pos)
	_floor()
	_place_crew()
	_build_buttons()
	_close_talk()
	day_panel.hide()
	modal = false
	acc = 0.0
	crew.refill()
	if saved.is_empty():
		_toast("Welcome, Pip. Build an inbound dock, a press and an outbound dock, and join them with conveyors. Press ? for the controls.")


func _on_contract(done: bool) -> void:
	if done:
		_toast("Contract shipped! Check the build bar for anything new.")
		_build_buttons()


func _on_quest(done: bool) -> void:
	if done:
		_toast("Quest finished.")


func _new_game() -> void:
	DirAccess.remove_absolute(SAVE)
	_start({})


func _next_day() -> void:
	day_panel.hide()
	modal = false


func _expand() -> void:
	if sim.expand():
		_floor()
		_build_buttons()
	else:
		_toast("Not enough money to expand.")


func _load() -> Dictionary:
	if FileAccess.file_exists(SAVE):
		var d = JSON.parse_string(FileAccess.get_file_as_string(SAVE))
		if d is Dictionary and d.has("sim") and d.has("stories") and d.has("player"):
			return d
	return {}


func _save() -> void:
	var f := FileAccess.open(SAVE, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify({"sim": sim.save(), "stories": crew.stories, "player": player_id}))


# ---------- the 3D world ----------

func _world() -> void:
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color("3b3a4a")
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color("c9c6e8")
	env.ambient_light_energy = 0.7
	var we := WorldEnvironment.new()
	we.environment = env
	add_child(we)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-55, 35, 0)
	sun.shadow_enabled = true
	add_child(sun)
	cam.projection = Camera3D.PROJECTION_ORTHOGONAL
	cam.far = 200.0
	add_child(cam)
	var fm := MultiMeshInstance3D.new()
	floor_mm.transform_format = MultiMesh.TRANSFORM_3D
	floor_mm.mesh = _mesh(MODELS + "floor.glb")
	fm.multimesh = floor_mm
	var fmat: BaseMaterial3D = floor_mm.mesh.surface_get_material(0).duplicate()
	fmat.albedo_color = Color(0.5, 0.5, 0.62)  # darker than the kit's floor, so machines and crates stand out
	fm.material_override = fmat
	add_child(fm)
	for id in ITEM_LOOK:
		var mm := MultiMesh.new()
		mm.transform_format = MultiMesh.TRANSFORM_3D
		mm.mesh = _mesh(MODELS + ITEM_LOOK[id][0] + ".glb")
		mm.instance_count = 1024  # shortcut: at most 1024 of one item are drawn, raise it if a floor ever holds more
		mm.visible_instance_count = 0
		var mi := MultiMeshInstance3D.new()
		mi.multimesh = mm
		var mat: BaseMaterial3D = mm.mesh.surface_get_material(0).duplicate()
		mat.albedo_color = ITEM_LOOK[id][2]
		mi.material_override = mat
		add_child(mi)
		item_mm[id] = mm
	add_child(ghost)


static func _mesh(path: String) -> Mesh:
	var n: Node = load(path).instantiate()
	var m: Mesh = n.find_children("*", "MeshInstance3D", true, false)[0].mesh
	n.free()
	return m


## Recolour every surface of a model (and optionally swap its palette texture) without touching the shared material.
static func _tint(n: Node, c: Color, tex: Texture2D = null) -> void:
	for mi in n.find_children("*", "MeshInstance3D", true, false):
		for i in mi.mesh.get_surface_count():
			var mat: BaseMaterial3D = mi.mesh.surface_get_material(i).duplicate()
			mat.albedo_color = c
			if tex != null:
				mat.albedo_texture = tex
			mi.set_surface_override_material(i, mat)


static func _center(pos: Vector2i) -> Vector3:
	return Vector3(pos.x + 0.5, 0.0, pos.y + 0.5)


func _model(kind: String, dir: int) -> Node3D:
	var look: Array = LOOK[kind]
	var n: Node3D = load(MODELS + look[0] + ".glb").instantiate()
	n.scale = Vector3.ONE * look[1]
	n.rotation.y = YAW0 - dir * PI / 2
	if look[2] != Color.WHITE:
		_tint(n, look[2])
	var arrow := Label3D.new()  # lies flat on top and points the way it sends things
	arrow.text = ">"
	arrow.font_size = 96
	arrow.outline_size = 24
	arrow.modulate = ORANGE
	arrow.pixel_size = 0.005 / look[1]
	arrow.rotation = Vector3(-PI / 2, -PI / 2, 0)
	arrow.position = Vector3(0, look[3], 0.0 if kind in ["belt", "splitter"] else 0.3) / look[1]
	n.add_child(arrow)
	return n


## Redraw the building at pos after it was built, turned or removed.
func _refresh(pos: Vector2i) -> void:
	if views.has(pos):
		views[pos].queue_free()
		views.erase(pos)
	if not sim.cells.has(pos):
		return
	var c: Dictionary = sim.cells[pos]
	var n := _model(c.kind, c.dir)
	n.position = _center(pos)
	if c.kind not in ["belt", "splitter"]:
		var tag := Label3D.new()
		tag.name = "tag"
		tag.billboard = BaseMaterial3D.BILLBOARD_ENABLED
		tag.no_depth_test = true
		tag.font_size = 40
		tag.outline_size = 10
		tag.pixel_size = 0.006 / n.scale.x
		tag.position = Vector3(0, (2.0 if c.kind in ["inbound", "outbound"] else 1.5) / n.scale.x, 0)
		n.add_child(tag)
	add_child(n)
	views[pos] = n


func _floor() -> void:
	floor_mm.instance_count = sim.floor_size.x * sim.floor_size.y
	for x in sim.floor_size.x:
		for y in sim.floor_size.y:
			floor_mm.set_instance_transform(x * sim.floor_size.y + y, Transform3D(Basis().scaled(Vector3.ONE * 0.96), _center(Vector2i(x, y))))


## The crew stand in a row along the back edge of the floor, Pip at the end.
func _place_crew() -> void:
	for n in crew_nodes.values():
		n.queue_free()
	crew_nodes = {}
	var ids: Array = Data.CREW.keys() + ["pip"]
	for i in ids.size():
		var id: String = ids[i]
		var n: Node3D = load(PEOPLE + (CREW_LOOK[id] if id != "pip" else "character-female-d") + ".glb").instantiate()
		n.scale = Vector3.ONE * 1.6
		n.position = Vector3(2.0 + i * 1.6, 0, -1.0)
		if id == "pip":
			_tint(n, Color.WHITE, load(PEOPLE + "colormap-blonde.png"))
		var ap: AnimationPlayer = n.find_children("*", "AnimationPlayer", true, false)[0]
		ap.get_animation("idle").loop_mode = Animation.LOOP_LINEAR
		ap.play("idle")
		ap.seek(i * 0.4)
		var tag := Label3D.new()
		tag.name = "tag"
		tag.billboard = BaseMaterial3D.BILLBOARD_ENABLED
		tag.no_depth_test = true
		tag.font_size = 40
		tag.outline_size = 10
		tag.pixel_size = 0.006 / n.scale.x
		tag.position = Vector3(0, 1.0, 0)
		tag.text = "Pip (you)" if id == "pip" else ""
		n.add_child(tag)
		add_child(n)
		crew_nodes[id] = n
	pip_goal = crew_nodes.pip.position


func _process(delta: float) -> void:
	if not modal and not sim.bankrupt():
		acc += delta * speed
		while acc >= TICK:
			acc -= TICK
			sim.step()
			if modal:
				acc = 0.0
				break
	_walk_pip(delta)
	_camera(delta)
	_draw_items(acc / TICK)
	_draw_tags()
	_draw_ghost()
	_hud()


## Pip strolls in a straight line to whatever was clicked last. She is not part of the sim, so she walks through things.
func _walk_pip(delta: float) -> void:
	var pip: Node3D = crew_nodes.pip
	var to := pip_goal - pip.position
	var moving := to.length() > 0.05
	if moving:
		pip.position += to.limit_length(4.0 * delta)
		pip.rotation.y = atan2(to.x, to.z)
	_play(pip, "walk" if moving else "idle")


## Loop an animation, or play one once and fall back to idle. Does nothing if that animation is already looping.
static func _play(n: Node3D, anim: String, once := false) -> void:
	var ap: AnimationPlayer = n.find_children("*", "AnimationPlayer", true, false)[0]
	if once:
		ap.play(anim)
		ap.queue("idle")
	elif ap.current_animation != anim and not ap.current_animation.begins_with("emote"):
		ap.get_animation(anim).loop_mode = Animation.LOOP_LINEAR
		ap.play(anim)


func _camera(delta: float) -> void:
	if not get_viewport().gui_get_focus_owner() is LineEdit:
		var move := Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
		if Input.is_physical_key_pressed(KEY_A): move.x -= 1
		if Input.is_physical_key_pressed(KEY_D): move.x += 1
		if Input.is_physical_key_pressed(KEY_W): move.y -= 1
		if Input.is_physical_key_pressed(KEY_S): move.y += 1
		pivot += Basis(Vector3.UP, yaw * PI / 2 + PI / 4) * Vector3(move.x, 0, move.y) * delta * zoom
	pivot = pivot.clamp(Vector3(-2, 0, -2), Vector3(sim.floor_size.x + 2, 0, sim.floor_size.y + 2))
	var b := Basis(Vector3.UP, yaw * PI / 2 + PI / 4) * Basis(Vector3.RIGHT, deg_to_rad(-40))
	cam.transform = Transform3D(b, pivot + b.z * 60.0)
	cam.size = zoom


func _draw_items(frac: float) -> void:
	var n := {}
	for id in item_mm:
		n[id] = 0
	for pos in sim.cells:
		var c: Dictionary = sim.cells[pos]
		if c.get("item", "") == "":
			continue
		var at := _center(pos)
		if c.at == sim.ticks:  # it arrived this tick: slide it in from where it came
			at = _center(c.from).lerp(at, frac)
		var s: float = ITEM_LOOK[c.item][1]
		if n[c.item] < 1024:
			item_mm[c.item].set_instance_transform(n[c.item], Transform3D(Basis().scaled(Vector3.ONE * s), at + Vector3(0, 0.4, 0)))
			n[c.item] += 1
	for id in item_mm:
		item_mm[id].visible_instance_count = n[id]


func _draw_tags() -> void:
	for pos in views:
		var tag = views[pos].get_node_or_null("tag")
		if tag != null:
			tag.text = _tag_text(sim.cells[pos])
	for id in Data.CREW:
		crew_nodes[id].get_node("tag").text = "%s %s %d" % [Data.CREW[id].name, {"low": ":(", "mid": ":|", "high": ":)"}[sim.mood(id)], int(sim.morale[id])]


## What floats over a building: what a dock handles, how full a hopper is, and for a machine only what is wrong.
func _tag_text(c: Dictionary) -> String:
	match c.kind:
		"inbound": return "IN: " + Data.ITEMS[c.raw].name
		"outbound": return "OUT"
		"hopper": return "%d/%d" % [c.store.size(), Data.HOPPER_CAP]
	if c.jam > 0:
		return "JAMMED"
	if c.out != "":
		return "blocked"
	if not c.busy:
		var need: Dictionary = Data.BUILD[c.kind]["in"]
		var missing: Array = need.keys().filter(func(i): return c.buf.get(i, 0) < need[i])
		if not missing.is_empty():
			return "needs " + " and ".join(missing.map(func(i): return Data.ITEMS[i].name))
	return ""


func _draw_ghost() -> void:
	var pos := _mouse_cell()
	var want := tool + str(tool_dir)
	if ghost_key != want:
		for ch in ghost.get_children():
			ch.queue_free()
		ghost_key = want
		if tool != "":
			ghost.add_child(_model(tool, tool_dir))
	ghost.visible = tool != "" and Rect2i(Vector2i.ZERO, sim.floor_size).has_point(pos)
	ghost.position = _center(pos) + Vector3(0, 0.05, 0)


func _mouse_cell() -> Vector2i:
	var p := _mouse_ground()
	return Vector2i(floori(p.x), floori(p.z))


func _mouse_ground() -> Vector3:
	var m := get_viewport().get_mouse_position()
	var o := cam.project_ray_origin(m)
	var d := cam.project_ray_normal(m)
	return o - d * (o.y / d.y)


# ---------- input ----------

func _unhandled_input(e: InputEvent) -> void:
	if e is InputEventMouseButton and e.pressed:
		match e.button_index:
			MOUSE_BUTTON_WHEEL_UP: zoom = maxf(6.0, zoom - 1.0)
			MOUSE_BUTTON_WHEEL_DOWN: zoom = minf(40.0, zoom + 1.0)
			MOUSE_BUTTON_LEFT: _click(_mouse_cell())
			MOUSE_BUTTON_RIGHT:
				if tool != "":
					tool = ""
				else:
					var pos := _mouse_cell()
					sim.demolish(pos)
					_refresh(pos)
	elif e is InputEventMouseMotion and e.button_mask & MOUSE_BUTTON_MASK_LEFT and tool == "belt":
		_click(_mouse_cell())  # drag to lay a run of conveyor
	elif e is InputEventMouseMotion and e.button_mask & MOUSE_BUTTON_MASK_MIDDLE:
		pivot -= Basis(Vector3.UP, yaw * PI / 2 + PI / 4) * Vector3(e.relative.x, 0, e.relative.y * 1.5) * zoom / 700.0
	elif e is InputEventKey and e.pressed and not e.echo:
		match e.physical_keycode:
			KEY_R:
				if tool != "":
					tool_dir = (tool_dir + 1) % 4
				else:
					sim.rotate(_mouse_cell())
					_refresh(_mouse_cell())
			KEY_Q: yaw = (yaw + 1) % 4
			KEY_E: yaw = (yaw + 3) % 4
			KEY_ESCAPE:
				tool = ""
				_close_talk()
			KEY_SPACE: speed = 0.0 if speed > 0.0 else 1.0


func _click(pos: Vector2i) -> void:
	if tool != "":
		if sim.build(tool, pos, tool_dir):
			_refresh(pos)
		elif not sim.cells.has(pos) and sim.money < Data.BUILD[tool].cost:
			_toast("Not enough money for that.")
		return
	var m := get_viewport().get_mouse_position()
	var o := cam.project_ray_origin(m)
	var d := cam.project_ray_normal(m)
	for id in crew_nodes:
		var to: Vector3 = crew_nodes[id].position + Vector3(0, 0.6, 0) - o
		if (to - d * to.dot(d)).length() < 0.7:  # the click's ray passes through this person
			if id == "pip":
				_toast("That's you: %s." % Data.PLAYER)
			else:
				_open_talk(id)
			return
	var c = sim.cells.get(pos)
	if c == null:
		return
	sim.quest_event("inspect", c.kind)
	pip_goal = _center(pos) + Vector3(0.0, 0, 0.8)
	if c.kind == "inbound":
		sim.cycle_raw(pos)
		_toast("This dock now orders %s (%d a crate)." % [Data.ITEMS[c.raw].name, Data.ITEMS[c.raw].buy])
	elif Data.BUILD[c.kind].has("in"):
		var b: Dictionary = Data.BUILD[c.kind]
		var needs: Array = b["in"].keys().map(func(i): return Data.ITEMS[i].name)
		_toast("%s: makes %s from %s.%s" % [b.name, Data.ITEMS[b.out].name, " and ".join(needs), " JAMMED!" if c.jam > 0 else ""])
	else:
		_toast("%s. R turns it, right-click removes it." % Data.BUILD[c.kind].name)


# ---------- the interface ----------

func _box(c: Color) -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = c
	s.set_corner_radius_all(8)
	s.set_content_margin_all(10)
	return s


func _button(text: String, parent: Node, act: Callable) -> Button:
	var b := Button.new()
	b.text = text
	b.focus_mode = Control.FOCUS_NONE
	b.add_theme_stylebox_override("normal", _box(Color("4a4870")))
	b.add_theme_stylebox_override("hover", _box(Color("5d5a8c")))
	b.add_theme_stylebox_override("pressed", _box(ORANGE))
	b.pressed.connect(act)
	parent.add_child(b)
	return b


func _panel(anchor: int, parent: Node, min_size := Vector2.ZERO) -> PanelContainer:
	var p := PanelContainer.new()
	p.add_theme_stylebox_override("panel", _box(Color(INK, 0.92)))
	p.custom_minimum_size = min_size
	parent.add_child(p)
	p.grow_horizontal = Control.GROW_DIRECTION_BEGIN if anchor == Control.PRESET_CENTER_RIGHT else Control.GROW_DIRECTION_BOTH
	p.grow_vertical = Control.GROW_DIRECTION_BEGIN if anchor == Control.PRESET_BOTTOM_WIDE else Control.GROW_DIRECTION_END if anchor == Control.PRESET_TOP_WIDE else Control.GROW_DIRECTION_BOTH
	p.set_anchors_and_offsets_preset(anchor, Control.PRESET_MODE_MINSIZE, 10)
	return p


func _ui() -> void:
	var ui := CanvasLayer.new()
	add_child(ui)
	var root := Control.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	ui.add_child(root)

	var bar := _panel(Control.PRESET_TOP_WIDE, root)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	bar.add_child(row)
	top = Label.new()
	row.add_child(top)
	day_bar = ProgressBar.new()
	day_bar.custom_minimum_size = Vector2(80, 0)
	day_bar.max_value = Data.TICKS_PER_DAY
	day_bar.show_percentage = false
	row.add_child(day_bar)
	var col := VBoxContainer.new()
	col.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(col)
	contract_label = Label.new()
	contract_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	col.add_child(contract_label)
	quest_label = Label.new()
	quest_label.add_theme_color_override("font_color", ORANGE)
	quest_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	col.add_child(quest_label)
	net_label = Label.new()
	row.add_child(net_label)
	for s in [["||", 0.0], [">", 1.0], [">>", 2.0], [">>>", 4.0]]:
		_button(s[0], row, func(): speed = s[1])
	_button("?", row, func(): _toast(HELP))
	_button("New game", row, _new_game)

	var bottom := _panel(Control.PRESET_BOTTOM_WIDE, root)
	build_bar = HBoxContainer.new()
	bottom.add_child(build_bar)

	toast = Label.new()
	toast.add_theme_stylebox_override("normal", _box(Color(INK, 0.92)))
	toast.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	toast.custom_minimum_size = Vector2(520, 0)
	root.add_child(toast)
	toast.set_anchors_and_offsets_preset(Control.PRESET_CENTER_BOTTOM, Control.PRESET_MODE_MINSIZE, 80)
	toast.grow_vertical = Control.GROW_DIRECTION_BEGIN
	toast.hide()

	talk_panel = _panel(Control.PRESET_CENTER_RIGHT, root, Vector2(380, 420))
	var tv := VBoxContainer.new()
	talk_panel.add_child(tv)
	talk_title = Label.new()
	talk_title.add_theme_color_override("font_color", ORANGE)
	tv.add_child(talk_title)
	talk_log = RichTextLabel.new()
	talk_log.size_flags_vertical = Control.SIZE_EXPAND_FILL
	talk_log.scroll_following = true
	tv.add_child(talk_log)
	raise_row = HBoxContainer.new()
	tv.add_child(raise_row)
	_button("Grant (+%d a day)" % Data.RAISE, raise_row, func(): _answer_raise(true))
	_button("Refuse", raise_row, func(): _answer_raise(false))
	var tb := HBoxContainer.new()
	tv.add_child(tb)
	_button("Any work?", tb, func(): _say_note(crew.offer_quest(talking)))
	_button("Offer a raise", tb, func(): raise_row.show())
	_button("Close", tb, _close_talk)
	talk_input = LineEdit.new()
	talk_input.placeholder_text = "Say something, then Enter"
	talk_input.max_length = 200
	talk_input.text_submitted.connect(_say)
	tv.add_child(talk_input)

	day_panel = _panel(Control.PRESET_CENTER, root, Vector2(460, 380))
	var dv := VBoxContainer.new()
	day_panel.add_child(dv)
	day_text = RichTextLabel.new()
	day_text.bbcode_enabled = true
	day_text.size_flags_vertical = Control.SIZE_EXPAND_FILL
	dv.add_child(day_text)
	_button("Start the next day", dv, _next_day)


func _build_buttons() -> void:
	for ch in build_bar.get_children():
		ch.queue_free()
	for kind in Data.BUILD:
		if kind in sim.unlocked:
			_button("%s %d" % [Data.BUILD[kind].name, Data.BUILD[kind].cost], build_bar, func(): tool = kind)
	_button("Bigger floor %d" % sim.expand_cost(), build_bar, _expand)


func _hud() -> void:
	top.text = "%d coins   Day %d   Crew morale %d" % [sim.money, sim.day, int(sim.team_morale())]
	day_bar.value = sim.tick
	var k: Dictionary = sim.contract
	contract_label.text = "Contract: %d/%d %s by the end of day %d, pays %d" % [k.done, k.qty, Data.ITEMS[k.item].name, k.due, k.reward]
	if sim.walkout:
		contract_label.text = "WALKOUT: the crew is too unhappy to work today.   " + contract_label.text
	if sim.bankrupt():
		contract_label.text = "BANKRUPT. The Hopper Works closes its doors. Press New game."
	elif sim.won():
		contract_label.text = "Hoppertunity seized! The Works is saved.   " + contract_label.text
	quest_label.visible = not sim.quest.is_empty()
	if not sim.quest.is_empty():
		var s: Dictionary = sim.quest.steps[sim.quest.step]
		quest_label.text = "Quest for %s: %s%s" % [Data.CREW[sim.quest.giver].name, s.get("description", ""),
				" (%d/%d)" % [sim.quest.have, sim.quest.need] if sim.quest.need > 1 else ""]
	net_label.text = "Anansi live" if crew.online else "Anansi offline"


func _toast(text: String) -> void:
	toast.text = text
	toast.show()
	var mine := text
	await get_tree().create_timer(5.0).timeout
	if toast.text == mine:
		toast.hide()


func _on_sold(pos: Vector2i, _item: String, amount: int) -> void:
	var l := Label3D.new()
	l.text = "+%d" % amount if amount > 0 else "returned!"
	l.modulate = ORANGE if amount > 0 else Color.TOMATO
	l.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	l.no_depth_test = true
	l.font_size = 40
	l.outline_size = 10
	l.position = _center(pos) + Vector3(0, 1.8, 0)
	add_child(l)
	var t := create_tween()
	t.tween_property(l, "position:y", 3.0, 0.8)
	t.tween_callback(l.queue_free)


func _on_day_end(s: Dictionary) -> void:
	modal = true
	_save()
	var lines := ["[b]End of day %d[/b]" % s.day, "",
			"Shipped: %d units%s" % [s.shipped, ", %d returned as defective" % s.defects if s.defects > 0 else ""],
			"Revenue: %d" % s.revenue, "Costs: %d (wages and rent %d)" % [s.costs, s.wages_rent],
			"[b]Net: %+d[/b]   Cash: %d" % [s.revenue - s.costs, sim.money], ""]
	if s.walkout:
		lines.append("The crew stayed home today. A day off cleared the air a little.")
	if s.missed:
		lines.append("[color=tomato]The contract deadline was missed. The customer took a penalty and Penny took the call.[/color]")
	if s.walkout_next:
		lines.append("[color=tomato]Morale is on the floor: the crew will not work tomorrow. Talk to them, help them, pay them.[/color]")
	for id in Data.CREW:
		lines.append("%s (%s): morale %d, wage %d" % [Data.CREW[id].name, Data.CREW[id].role, int(sim.morale[id]), sim.wages[id]])
	day_text.text = "\n".join(lines)
	day_panel.show()
	crew.refill()


# ---------- talking ----------

func _open_talk(id: String) -> void:
	talking = id
	tool = ""
	pip_goal = crew_nodes[id].position + Vector3(0.3, 0, 1.2)
	talk_title.text = "%s, %s" % [Data.CREW[id].name, Data.CREW[id].role]
	talk_log.clear()
	raise_row.hide()
	talk_panel.show()
	talk_input.grab_focus()
	sim.quest_event("talk_to", id)
	_log(Data.CREW[id].name, crew.line(id))
	var beat := crew.story_beat(id)
	if beat != "":
		_log("", beat)


func _close_talk() -> void:
	talking = ""
	talk_panel.hide()
	talk_input.release_focus()


func _log(who: String, text: String) -> void:
	talk_log.add_text(("%s: " % who if who != "" else "~ ") + text + "\n\n")


func _say_note(note: String) -> void:
	if note != "":
		_log("", note)


func _say(text: String) -> void:
	text = text.strip_edges()
	if text == "" or talking == "":
		return
	var id := talking
	talk_input.text = ""
	talk_input.editable = false
	talk_input.placeholder_text = "%s is thinking..." % Data.CREW[id].name
	_log("Pip", text)
	var r: Dictionary = await crew.talk(id, text)
	talk_input.editable = true
	talk_input.placeholder_text = "Say something, then Enter"
	if talking != id:
		return
	talk_input.grab_focus()
	_log(Data.CREW[id].name, r.say)
	_say_note(r.note)
	if r.note.contains("morale"):
		_play(crew_nodes[id], "emote-yes" if r.note.contains("rises") else "emote-no", true)
	if r.raise:
		_log("", "%s is asking for a raise." % Data.CREW[id].name)
		raise_row.show()


func _answer_raise(grant: bool) -> void:
	raise_row.hide()
	sim.answer_raise(talking, grant)
	_play(crew_nodes[talking], "emote-yes" if grant else "emote-no", true)
	_log("", "You %s. %s's wage is %d a day." % ["agree" if grant else "say no", Data.CREW[talking].name, sim.wages[talking]])
