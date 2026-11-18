// node examples/hoppertunity/tools/publish_pages.mjs OUTDIR: makes OUTDIR, a clone of the public avielbaum/hoppertunity repo, match
// examples/hoppertunity as committed on this checkout's HEAD (main): every tracked file except the gateway config, this folder's
// README and tools/, with the comments that point into the Anansi repo reworded. OUTDIR keeps its own .git, .github and README.md.
// The public repo's pages.yml runs this every day against Anansi's main, so that repo needs no hand syncing.
import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const out = process.argv[2];
if (!out) { console.error("usage: node examples/hoppertunity/tools/publish_pages.mjs OUTDIR"); process.exit(1); }
const game = resolve(dirname(fileURLToPath(import.meta.url)), ".."), dest = resolve(out);
const ours = (f) => f.startsWith(".github/") || f === "README.md";  // the public repo's own files
const skip = (f) => f === "README.md" || f === "config.hoppertunity.json" || f.startsWith("tools/");
// Every edit must still apply: if the wording changed in Anansi, update the edit here rather than publish a pointer that leads nowhere.
const EDITS = {
  "assets/LICENSE.md": [["The example's code is MIT or Apache-2.0 (see `examples/hoppertunity/LICENSE-MIT`", "The code is MIT or Apache-2.0 (see `LICENSE-MIT`"]],
  "src/crew.gd": [["(config.hoppertunity.json; test/checks.gd\n## keeps them equal)", "(the Anansi repository's tests keep them\n## equal to its gateway config)"],
                  ["system_prefix (config.hoppertunity.json).", "system_prefix."]],
  "src/data.gd": [["same names (config.hoppertunity.json).", "same names."]],
  "test/run.gd": [["--path examples/hoppertunity", "--path ."]],
  "test/shot.gd": [["--path examples/hoppertunity", "--path ."]],
  "test/web.mjs": [["node examples/hoppertunity/test/web.mjs", "node test/web.mjs"]],
};
const git = (cwd, ...args) => execFileSync("git", args, { cwd, maxBuffer: 1 << 28 });
const list = (cwd) => git(cwd, "ls-files", "-z").toString().split("\0").filter(Boolean);

const files = list(game).filter((f) => !skip(f));
for (const f of list(dest)) if (!ours(f) && !files.includes(f)) rmSync(join(dest, f), { force: true });  // deleted in Anansi
for (const f of files) {
  let data = git(game, "show", `HEAD:./${f}`);  // the committed blob: no local edits, no CRLF from a Windows checkout
  for (const [from, to] of EDITS[f] || []) {
    const text = data.toString("utf8");
    if (!text.includes(from)) throw new Error(`${f}: expected text not found, update EDITS in publish_pages.mjs: ${JSON.stringify(from)}`);
    data = Buffer.from(text.replace(from, to), "utf8");
  }
  mkdirSync(dirname(join(dest, f)), { recursive: true });
  writeFileSync(join(dest, f), data);
}
for (const f of Object.keys(EDITS)) if (!files.includes(f)) throw new Error(`${f} is gone from examples/hoppertunity: remove it from EDITS`);
console.log(`synced ${files.length} files from examples/hoppertunity at ${git(game, "rev-parse", "--short", "HEAD").toString().trim()} into ${dest}`);
