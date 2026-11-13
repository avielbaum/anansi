# Examples

Example games built on the Anansi SDKs, one folder per example. Each folder has its own README with run instructions,
its own `LICENSE-MIT` and `LICENSE-APACHE` for the code, and an `assets/LICENSE.md` for any third-party art.

| Example | SDK | What it shows |
|---|---|---|
| [waypoint](waypoint/) | JavaScript (`sdk/js`), browser, Phaser 3 | A 16-bit-style JRPG: a town, a dungeon, side-view battles with time gauges, a menu and saves. NPCs answer free text and hand out generated side quests through `anansi.chat` and `anansi.quest`, and you can teleport to any real place you type, which becomes a generated town; all of it has written fallbacks offline. `prototype/` is an earlier canvas version built around real-world destinations. |

To add an example, create `examples/<name>/` with a README, the two licence files and, if it ships art,
`assets/LICENSE.md` with the art's licences and credits. Only use art that may be redistributed (CC0, CC-BY, OGA-BY,
CC-BY-SA); see [LICENSING.md](../LICENSING.md).
