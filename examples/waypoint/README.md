# Waypoint

A browser JRPG in the 16-bit style: Phaser 3, LPC character art, side-view battles where each character acts when
their gauge fills, and NPCs and side quests powered by Anansi through the JavaScript SDK (`sdk/js`). The earlier canvas
prototype, with real-world destinations, is in `prototype/`.

**Milestone 1, the vertical slice:**

- **Title:** New Game, or Continue from a save. **Lead choice:** Kai or Mira; the other one becomes the companion and follows you.
- **Old Town:** houses, a plaza, a street, a shopkeeper (buy Potions and Ethers, or rest for 10 G), a townsperson, and a
  Directorate agent who pressures you. Their lines change after the boss.
- **The Undercroft:** tunnels with random encounters, two chests, and the Warden boss.
- **Battles:** side view, with a gauge per fighter (time waits while you choose). Commands are Fight, Skill, Item, Defend
  and Flee. Kai has Blink Strike and Rift Burst; Mira has Mend and Static Lance. You earn XP, gold and level-ups; losing
  returns you to the title.
- **Menu** (Esc or X): Items, Status, Quests, Teleport, Save.

**Milestone 2, Anansi in town:**

- **Ask…:** type anything to Tobias, Ines or Agent Kessler, and they answer in character (`anansi.chat`, structured).
  The NPC knows the story so far and your current quest. Ines can patch you up (`heal_hero`), and Tobias or Ines can
  hand you a Potion (`give_supplies`), each at most once per visit. Kessler never helps.
- **Any work?:** Ines offers side quests that `anansi.quest` builds only from this town's people, places and items
  (`QUEST_WORLD` in `src/data.js`). Steps are talk to someone, go somewhere, or find an item, which sparkles on the map
  while a quest asks for it. Rewards follow the quest's tier (`small`, `medium`, `large`). Each finished quest's summary
  becomes the story so far for the next one.
- **No waiting, no stalling:** the next quest is generated in the background as soon as you are on a map (30 to 60 s
  on CPU), so it is usually ready when you ask. Without a gateway, NPCs answer with written lines and Ines hands out
  three written quests.
- **Tidying:** quest text from a small model gets raw ids replaced by names and stray CJK characters removed
  (`tidyQuest`), and the game checks again that every step targets something it has (`questFits`).

**Milestone 3, real-world cities:**

- **Teleport** (in the menu): to Old Town, to a city you have been to, or to any real place you type. The
  `waypoint-atlas` gateway title answers with real landmarks, local first names and jobs, local things, a one-line
  vibe and a climate (temperate, desert, snow or tropical). That takes about 10 s on CPU; a gateway answer is cached in
  the browser, so going back to a place is instant.
- **A town built from it:** `genCity` (`src/city.js`) lays out a street, a plaza, houses and trees from a seed made
  from the city's name, so a city always looks the same. The climate picks the ground (grass, sand, snow or lush
  green), the three landmarks name three districts, and three locals and Agent Kessler stand where the party can
  reach them. Only the atlas is saved; the town is rebuilt from it when you load.
- **Everything from Old Town works there:** Ask… (each local knows the city and your quest), Any work? from the first
  local (a quest built from that city's people, places and items), sparkling items, rewards, and Directorate drones
  as random encounters. A quest only moves forward in its own city, and a local reminds you if you still owe a job
  elsewhere. The one-gift limit is kept per city.
- **Without a gateway:** the city gets generic parts (Nia, Marco and Iris, "the old quarter of ...") and written quests.
- **Limits:** a 1.7B model got the climate right for 7 of 8 test cities, and it sometimes invents place names or
  gives jobs instead of names (a job-only entry gets a generic first name). A larger model behind the same gateway
  does better. A city made while the gateway was down stays generic until you type its name in Teleport again.

Controls: arrows or WASD to move; Enter, Space or Z to talk and confirm; Esc or X for the menu and to go back.

Code: `src/rules.js` (stats, damage, levelling, quests; no Phaser, tested by `check.mjs`), `src/data.js` (the written
maps, dialogue, quest world, personas), `src/atlas.js` (parsing what the model says about a place; the prototype
shares it), `src/city.js` (generating a city's map, people and written quests), `src/world.js` (which map and quest area
an id belongs to), `src/anansi.js` (the SDK calls), `src/field.js`, `src/battle.js`, `src/menu.js`, `src/ui.js`
(windows, dialogue, text box, choosers), `src/state.js` (save). `check.mjs` walks every map tile by tile, written or
generated, to prove that each exit, chest, person, quest item and the boss can be reached; it generates 56 cities,
including one from an empty atlas.

## Run

From the `anansi` folder, with Ollama running and `qwen3:1.7b` pulled, start the gateway:

```bash
ANANSI_CONFIG=examples/waypoint/config.waypoint.json python -m uvicorn gateway.app:make_app --factory --port 8080
```

and, in a second terminal, serve the files:

```bash
python -m http.server 8000
```

Open http://localhost:8000/examples/waypoint/ . Without the gateway, the game still runs, using the written lines and
quests. Query parameters: `?gateway=URL&key=KEY`. Self-check: `node examples/waypoint/check.mjs`.

## Characters

`tools/cast.json` describes each character as LPC layers plus colours. `python tools/build_sprites.py` downloads the
layers from the [Universal LPC Spritesheet Character Generator](https://github.com/LiberatedPixelCup/Universal-LPC-Spritesheet-Character-Generator)
(cached outside the repo), recolours and stacks them, and writes `assets/sprites/<id>/<animation>.png` (64x64 frames;
rows face up, left, down, right) and `assets/CREDITS.csv`.

The outfits used so far have walk, slash, thrust, spellcast and hurt, but not idle, run or combat stance. The build
skips an animation when any layer lacks it, so no character is drawn half dressed.

## Tiles, enemies and backgrounds

`python tools/build_tiles.py` bakes ground textures, a house front, trees, dungeon pieces, 15 enemy cut-outs and two
battle backgrounds into `assets/tiles` and `assets/enemies`. It reads the downloaded packs from `../../../_assets_dl`
(or `--src`): LPC Base Assets and LPC in-battle sprites (CC-BY-SA 3.0 / GPL 3.0), curato's street tiles (CC0) and
Pixel-boy's battlebacks (CC0). Credits are in `assets/CREDITS_TILES.csv`. The baked files are committed, so the game
runs without the downloads.

## Licences

The code (`src/`, `tools/`, `check.mjs`, `index.html`, `prototype/`) is MIT or Apache-2.0 ([LICENSE-MIT](LICENSE-MIT),
[LICENSE-APACHE](LICENSE-APACHE)). The prototype talks to an Anansi gateway, which is under PolyForm Noncommercial
(see [LICENSING.md](../../LICENSING.md)). The art in `assets/` keeps its own licences: CC-BY-SA 3.0 for the LPC characters, enemies and tiles, and
CC0 for the street tiles and battle backgrounds. See [assets/LICENSE.md](assets/LICENSE.md). The two CREDITS files must
ship with the game.
