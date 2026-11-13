# Waypoint

A browser JRPG in the 16-bit style: Phaser 3, LPC character art, side-view battles where each character acts when
their gauge fills. The plan is a vertical slice first, offline: a town, a dungeon, menus and battles. After that come
Anansi dialogue, real-world cities and the story. The earlier canvas prototype, which already talks to Anansi, is in
`prototype/`.

Milestone 1, the vertical slice, is playable:

- **Title:** New Game, or Continue from a save. **Lead choice:** Kai or Mira; the other one becomes the companion and follows you.
- **Old Town:** houses, a plaza, a street, a shopkeeper (buy Potions and Ethers, or rest for 10 G), a townsperson, and a
  Directorate agent who pressures you. Their lines change after the boss.
- **The Undercroft:** tunnels with random encounters, two chests, and the Warden boss.
- **Battles:** side view, with a gauge per fighter (time waits while you choose). Commands are Fight, Skill, Item, Defend
  and Flee. Kai has Blink Strike and Rift Burst; Mira has Mend and Static Lance. You earn XP, gold and level-ups; losing
  returns you to the title.
- **Menu** (Esc or X): Items, Status, Save.

Controls: arrows or WASD to move; Enter, Space or Z to talk and confirm; Esc or X for the menu and to go back.

Code: `src/rules.js` (stats, damage, levelling; no Phaser, tested by `check.mjs`), `src/data.js` (maps, dialogue),
`src/field.js`, `src/battle.js`, `src/menu.js`, `src/ui.js` (windows, dialogue, choosers), `src/state.js` (save).
`check.mjs` also walks every map tile by tile, to prove that each exit, chest, NPC and the boss can be reached.

## Run

From the `anansi` folder:

```bash
python -m http.server 8000
```

Open http://localhost:8000/examples/waypoint/ . Self-check: `node examples/waypoint/check.mjs`.

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
