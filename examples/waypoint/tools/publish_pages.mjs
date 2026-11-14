// node tools/publish_pages.mjs OUTDIR: copies just what the browser needs to run Waypoint (and the licences and credits that must
// travel with it) into OUTDIR, keeping the repo's folder layout so that src/anansi.js can still import ../../../sdk/js/anansi.mjs.
// OUTDIR then holds a static site: commit it to a public repo and serve it with GitHub Pages (free for public repos).
import { cpSync, mkdirSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { resolve, join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const out = process.argv[2];
if (!out) { console.error("usage: node tools/publish_pages.mjs OUTDIR"); process.exit(1); }
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const game = join(root, "examples", "waypoint"), dest = resolve(out);
for (const f of existsSync(dest) ? ["examples", "sdk", "index.html", "README.md", ".nojekyll"] : []) rmSync(join(dest, f), { recursive: true, force: true }); // keep .git
const copy = (from, to) => { mkdirSync(dirname(join(dest, to)), { recursive: true }); cpSync(join(root, from), join(dest, to), { recursive: true }); };
for (const f of ["index.html", "src", "assets", "LICENSE-MIT", "LICENSE-APACHE"]) copy(`examples/waypoint/${f}`, `examples/waypoint/${f}`);
for (const f of ["anansi.mjs", "LICENSE-MIT", "LICENSE-APACHE"]) copy(`sdk/js/${f}`, `sdk/js/${f}`);
writeFileSync(join(dest, ".nojekyll"), "");
writeFileSync(join(dest, "index.html"), '<!doctype html><meta charset="utf-8"><title>Waypoint</title><meta http-equiv="refresh" content="0; url=examples/waypoint/"><a href="examples/waypoint/">Play Waypoint</a>\n');
writeFileSync(join(dest, "README.md"), `# Waypoint

A browser JRPG made with the Anansi SDK. This repository is a static build of \`examples/waypoint\` from the Anansi project, served with GitHub Pages.
Without an Anansi gateway the game uses its written fallbacks for city details, NPC chat and side quests.

- Game code and the SDK: MIT OR Apache-2.0 (see \`examples/waypoint/LICENSE-*\` and \`sdk/js/LICENSE-*\`).
- Art, tiles, icons and audio keep their own licences: see \`examples/waypoint/assets/LICENSE.md\` and the \`CREDITS*.csv\` files beside it.
  Character art is CC-BY-SA 3.0 (Liberated Pixel Cup); Phaser is loaded from a CDN.
`);
console.log("wrote", dest);
