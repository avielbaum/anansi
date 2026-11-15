# Hoppertunity

A 3D factory tycoon for the browser: Godot 4.3, the Compatibility renderer (WebGL 2), Kenney's CC0 art, and a crew of
coworkers who talk, hand out quests and tell their stories through Anansi (`sdk/godot`). You are Pip Hopper, the new
floor manager of the Hopper Works, a small gadget plant on its last chance.

![A small Hoppertunity factory: docks, conveyors, a hopper, machines and the crew](docs/screenshot.png)

## The game

- **Build a line:** inbound docks order raw materials, conveyors and splitters move them, hoppers buffer them, six
  kinds of machine turn them into goods, and outbound docks sell them. Steel becomes panels, plastic becomes casings,
  the two become gadgets, and gadgets are boxed; later, copper wire becomes coils and gadgets with coils become smart
  gadgets. Belts back up, docks stop
  ordering when there is nowhere to unload, and you pay only for crates that arrive.
- **Contracts:** ship a set number of one product before the deadline for a bonus. Each finished contract unlocks the
  next machine and material; five finished contracts save the plant, and the coil winder and the fitter arrive around
  then for whoever keeps playing. A missed deadline costs a penalty. After each
  one, Penny lines up the next: sour (morale under 35) she has one customer; otherwise you also get a rush job (less
  to ship, less time, less pay), and when she is happy (60 or more) a bulk order too.
- **Days:** a day is one minute at normal speed. At the end you pay wages, rent and 5 coins of upkeep per machine,
  and see the day's profit (building spend is listed apart), each coworker's morale and wage, and a chart of the last
  two weeks. Fall 500 coins into debt and the Works closes.
- **Events:** from day 3, some mornings bring news: a late truck slows the docks, a power dip slows the machines, a
  trade fair lifts prices, an inspector fines a loose cable. A coworker at morale 70 or more heads off their own kind
  of trouble. Coworkers are told the day's news, so you can talk to them about it.
- **Upgrades:** five one-off improvements (break room, dock crane, better tooling, quality scanner, showroom) give
  spare cash somewhere to go.
- **Crew sheet:** the Crew button lists everyone's morale, what that does to their work, pay, errands done and how far
  their story has got.
- **Tutorial:** eight steps walk a new manager from the first dock to the first errand, pulsing the button to press.
  It can be skipped, and a saved game remembers where you were.
- **Trouble shows:** a machine that is jammed, blocked or short of an input says so above it. Whoever or whatever the
  current errand step wants is marked in orange.
- **The crew:** Dot (docks), Sprocket (machines), Tilly (packing and quality) and Penny (sales) walk between the
  buildings they look after, and each have a morale from 0 to 100. Morale scales their station from 0.8x to 1.2x: truck turnaround, machine speed and jams, defective units
  that come back unpaid, and selling prices. Everyone loses 3 morale on an ordinary day, so a crew left alone sours.
  Below 30 on average the crew walks out for a day; above 70 everything sells for 10% more.

## What Anansi does

The model picks words and one whitelisted action. The game owns every number (`src/sim.gd`), so nothing a model says
can do more than the table below.

| Call | When | Effect in the game |
|---|---|---|
| `chat` (structured) | You type to a coworker | `morale_up` / `morale_down`: 5 morale, at most 10 a day per coworker. `offer_quest`: starts their quest. `share_tip`: reveals the next contract. `ask_raise`: asks you for a raise (you decide: +5 wage a day and +15 morale, or -10 morale). |
| `quest` | Generated ahead of time, one per coworker | Steps are `talk_to` a coworker, `inspect` a station or `deliver` goods, built only from what your plant has unlocked. The reward tier pays 60, 140 or 280 coins and lifts the giver's morale; a medium or large one also leaves them fired up, their station running a fifth faster for a day or two. |
| `chat_stream` | At the end of each day | The coworker with the lowest morale says a word about the day under the day's report, sentence by sentence. A streamed reply carries no action, so it changes nothing in the game. Only tried when the gateway answered last time; otherwise a written line appears at once. |
| `storyline` | Once per coworker at the start of a game | Four beats, told one at a time as you finish that coworker's quests. The last beat gives a permanent perk (no more jams, no more defects, faster docks, better prices). |

Each coworker is sent who they are, their morale, the day, the cash and the contract, so what they say fits the plant.
**Without a gateway the game plays the same:** written lines by mood, written quests and four written stories
(`src/data.gd`: twelve quests, three per coworker). The Any work? and Offer a raise buttons work either way. The top bar shows whether the last answer
was live.

### Tried with a real model

With Ollama's `qwen3:1.7b` on a laptop CPU, through this example's gateway config (one run of each, by hand; a spot
check, not an evaluation):

- **Chat:** five different lines to Dot (praise, "got any work?", an insult, "any big orders coming up?", "let us talk
  about your pay") came back in character with `morale_up`, `offer_quest`, `morale_down`, `share_tip` and `ask_raise`.
  Before `action_gates` were added to the config, a compliment once came back as `offer_quest`. A reply takes 10 to
  40 s; the chat timeout is 75 s, and background generation waits while a conversation is open.
- **Quests:** 20 to 30 s each. Asked only with the coworker's role as the theme, every quest was the same errand for
  nobody in particular; asked for "a favour that Sprocket, the machine technician, asks of the new manager" it wrote
  "A Favor for Sprocket". Quests may only name buildings standing on the floor and goods the plant makes, and every
  generated quest passed the game's own check.
- **Day-end remark (streamed):** "The day went smoothly, but we had a few issues with defects. We'll need to focus on
  improving quality and efficiency to meet our goals." First sentence after 8 s, second 1.2 s later.
- **Storylines:** about 38 s. A plain theme gave a tour of the plant; asking for "a worry they carry from their past,
  something that stirs it up, a turning point, and how it is put to rest" gave four beats about an old mistake and a
  father. The written stories in `src/data.gd` are still tighter.

## Run it

You need [Godot 4.3](https://godotengine.org/download/archive/4.3-stable/) (the version CI uses).

```
godot --path examples/hoppertunity                    # play on the desktop
```

In the browser (install the 4.3 web export template in the editor first: Editor > Manage Export Templates):

```
godot --headless --path examples/hoppertunity --export-release Web build/web/index.html
python -m http.server 8000 --directory examples/hoppertunity/build/web
```

Then open http://localhost:8000. The export is single-threaded, so any static server works.

For live coworkers, run a local gateway with this example's title (it expects Ollama with `qwen3:1.7b` on port 11434;
edit `nodes` in the config for another model server):

```
ANANSI_CONFIG=examples/hoppertunity/config.hoppertunity.json python -m uvicorn gateway.app:make_app --factory --port 8080
```

The game talks to `http://127.0.0.1:8080` (`GATEWAY` in `src/main.gd`), and the config allows the page origins
`http://localhost:8000` and `http://127.0.0.1:8000`. This is a local demo: it uses `dev` auth and ships the example
title key, so do not put it on the public internet as it is (see `docs/sdk.md`, Browsers).

## Controls

Click a build button (or press its number), then the floor. Hover a button to read what the building does. **R** turns the piece (or the building under the mouse), right-click cancels
the tool or removes a building for half its price. Drag to lay conveyor. Click a coworker to talk, a building to
inspect it, an inbound dock to change what it orders. **WASD** or the arrows move the view, **Q**/**E** turn it, the
wheel zooms, **Space** pauses, **M** mutes everything, **N** just the music. The **?** button has the controls and two volume sliders, which are
remembered.

Everything the keyboard, wheel and right button do also has a button in the bottom bar (Turn, Remove, +, -, View),
clicking a build button again puts the tool away, and dragging the floor moves the view. That is meant to make the game
playable on a touch screen; it was tried with a mouse only, never on a real phone or tablet.

## Code

| File | What it holds |
|---|---|
| `src/data.gd` | Every number and every written word: items, machines, contracts, the crew, fallback lines, quests, stories |
| `src/sim.gd` | The whole game as plain data on a fixed tick: no nodes, so it runs headless and saves as one dictionary |
| `src/crew.gd` | Every Anansi call, and what each answer may do to the sim |
| `src/main.gd` | The 3D view, input, interface (title, day-end, contract choice, win and lose screens), tutorial and sound, all built in code |
| `addons/anansi` | A copy of `sdk/godot/addons/anansi`; CI fails if the two differ |
| `test/checks.gd` | Self-checks: `godot --headless --path examples/hoppertunity --script res://test/run.gd` |

CI (`.github/workflows/ci.yml`, job `godot`) runs the self-checks against a gateway serving this title on mock nodes,
and exports the web build. The checks include two scripted playthroughs of one production line: a manager who gives a
raise whenever someone's morale sags wins on day 9 without going into debt; one who ignores the crew gets four walkouts,
misses three deadlines and has not won by day 20. A third keeps playing after the win, always taking the
biggest order on offer, buying upgrades with spare cash and building the coil and smart-gadget line: it ships the
seventh contract on day 15 with four upgrades and about 2,000 coins left, having missed two deadlines through greed. A full 28x24 floor of moving belts ticks in under 5 ms on a laptop.
The last check starts the real game scene and drives it through its screens (title, building, two days, day-end reports,
talking with no gateway, an errand, a raise, upgrades, the crew sheet, a bigger floor), so a script error in the interface
fails CI too; headless nothing is drawn, so it does not check what any of it looks like.
A last CI step opens the exported web build in headless Chrome with software WebGL (`test/web.mjs`, Node 22+) and
checks that the page logs no script error, the main loop runs, and the middle of the full stress floor is not one
flat colour: the failure that hit the browser build twice while the desktop build was fine.

## Not done yet

- Forklifts. People walk around buildings (Godot's `AStarGrid2D`), but not around each other, and where they stand
  changes nothing in the sim.
- The sound effects (Kenney, CC0) and the music loop ("Bossa Nova" by Joth, CC0) were chosen by name and wired up on
  a machine with no audio device: nobody has listened to them in the game yet.
- The browser build was run by hand in Chrome on a 2013 laptop GPU (Quadro K1100M), without a gateway and with one
  (Ollama, `qwen3:1.7b` on CPU). It held 55 frames a second for
  a new game and for the largest floor with every tile a moving conveyor (`?stress` in the address, or `-- stress` on
  the desktop; **F3** shows the frame rate). CI exports the web build and checks in headless Chrome that it runs and draws (see Code, below).
- A few hundred `Label3D` nodes make the browser build draw no 3D at all (672 labelled buildings: blank; the same
  672 without labels: fine; the desktop build never minded). So building tags are painted on one 2D overlay, and
  conveyors and arrows are drawn in four batches. With that, 672 hoppers (`?stress&fill=hopper`) also hold 55 frames a
  second. Only the "+8" sale pop-ups are still `Label3D`, a handful at a time.
- Conversations arrive whole (`chat`), because the game needs the action and a streamed reply carries none; the
  day-end remark is the streamed one. In the desktop build against the real model its two sentences arrived 1.2 s
  apart (8.0 s and 9.2 s), and in the browser build in Chrome also 1.2 s apart (4.2 s and 5.4 s; `?remark` in the
  address prints the timings to the console). So the Godot SDK streams sentence by sentence in a browser too. Its own
  18 checks, exported for the web from a scratch copy, also all passed in Chrome against a gateway on mock nodes.
