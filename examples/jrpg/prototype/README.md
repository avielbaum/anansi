# Waypoint: a teleporting travel JRPG on Anansi

You can teleport anywhere you can picture. The Directorate, a shadowy government agency, wants that power for its
own operations. You have three jumps to lose them, and the third ends in a fight with the Director.

You choose every destination. Type any real place, and the game builds it from what the model knows:

1. **Atlas** (`atlas.chat`, title `waypoint-atlas`): real landmarks, local people with jobs, local items and a one-line
   vibe, in a four-line format that `parseAtlas` reads (`world.mjs`). Missing entries are filled with generic ones.
2. **Map** (`genMap`): three districts, one per landmark, laid out from a seed made from the place name, so the same
   city always gives the same streets.
3. **Quest** (`anansi.quest`): built only from that city's people, places and items plus Agent Kessler, with the
   story so far carried from jump to jump.
4. **Dialogue** (`anansi.chat`, structured): talk freely to locals, who know the city and your current goal. Locals can
   `heal_hero` or `give_supplies`. Kessler only pressures you, and after each escape you hear his intercepted message.

Teleporting is the core mechanic. Press T on the map to blink up to 3 tiles through walls and water. In battle you
can blink-strike for double damage or teleport out (both cost energy). If the gateway is down, the game still runs
on generic districts and authored quests.

## Run

From the `anansi` folder, with Ollama running and `qwen3:1.7b` pulled:

```bash
ANANSI_CONFIG=examples/jrpg/prototype/config.jrpg.json python -m uvicorn gateway.app:make_app --factory --port 8080
```

```bash
python -m http.server 8000
```

Open http://localhost:8000/examples/jrpg/prototype/ . Optional query parameters: `?gateway=URL&key=KEY`.

Controls: arrows or WASD to move, T to blink, E to talk, 1 to 4 in battle. Self-check: `node examples/jrpg/prototype/check.mjs`.

On CPU, each jump takes about a minute (atlas, then quest). A 1.7B model knows famous cities well and small ones
poorly, and sometimes misspells names. The title keys are in the page, which is fine for a local dev gateway but not
for a shipped game.
