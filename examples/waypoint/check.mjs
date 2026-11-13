// node check.mjs: rules, data and maps agree; every exit, chest, NPC and boss can be reached on foot.
import assert from "node:assert";
import { readFileSync, existsSync } from "node:fs";
import { damage, gainXp, newHero, newGame, atbFill, useItem, xpToNext, ENEMIES, HEROES, SKILLS, questStep, payQuest, questFits, tidyQuest } from "./src/rules.js";
import { MAPS, STAMPS, TALK, QUEST_WORLD, REGIONS, ITEM_SPOTS, PERSONAS, FALLBACK_QUESTS, SHORT_NAMES } from "./src/data.js";
import { pages } from "./src/ui.js";

// long dialogue splits into pages that fit the box, losing no words
const long = "The Whispering Tram. Kai stumbles into a quiet town where the Directorate watches from afar. Tobias, the shopkeeper, offers a job to help retrieve a lost letter. Ines reveals a secret about the tram token. Agent Kessler watches from the shadows, waiting for the right moment.";
const pg = pages(long, 180);
assert(pg.length > 1 && pg.every(p => p.length <= 180), "pages fit");
assert.equal(pg.join(" "), long, "no words lost");
assert.deepEqual(pages("Short line.", 180), ["Short line."]);
assert(pages("x".repeat(50) + " " + "y".repeat(50), 60).every(p => p.length <= 60));

const here = p => new URL(p, import.meta.url);
const cast = JSON.parse(readFileSync(here("assets/sprites/manifest.json")));

// sprites: what the field and battle use
for (const id of ["lead_m", "lead_f", "agent", "shopkeeper", "local_f"]) {
  assert.deepEqual(cast[id]?.anims.walk, { frames: 9, rows: 4 }, `${id} walk; run python tools/build_sprites.py`);
  if (HEROES[id]) for (const a of ["slash", "thrust", "spellcast", "hurt"]) assert(cast[id].anims[a], `${id} lacks ${a}`);
}
const credits = readFileSync(here("assets/CREDITS.csv"), "utf8");
for (const part of ["body/bodies/male", "body/bodies/female", "hair/ponytail", "torso/jacket/trench"]) assert(credits.includes(part), `credits miss ${part}`);
assert(existsSync(here("assets/CREDITS_TILES.csv")), "run python tools/build_tiles.py");

// rules
assert.equal(damage(10, 5, 1, () => 0.5), 15);
assert.equal(damage(1, 50, 1, () => 0), 1, "damage is at least 1");
assert.equal(damage(10, 5, 1, () => 0.5, true), 8, "defending halves");
const t = atbFill(10, 1000); assert(t > 30 && t < 36, "speed 10 fills the gauge in about 3 s");
const k = newHero("lead_m");
assert.equal(gainXp(k, xpToNext(1) + xpToNext(2)), 2); assert.equal(k.lvl, 3); assert.equal(k.maxhp, 62 + 2 * 9);
k.hp = 10; assert(useItem("potion", k)); assert.equal(k.hp, 50);
k.hp = 0; assert(!useItem("potion", k), "items do not raise the fallen");
const g = newGame("lead_f"); assert.deepEqual(g.party.map(h => h.id), ["lead_f", "lead_m"], "the chosen lead comes first");
for (const h of Object.values(HEROES)) for (const s of h.skills) assert(SKILLS[s], s);

// maps
const opens = {}, seens = {};
for (const [mid, M] of Object.entries(MAPS)) {
  const T = 32, solids = [];
  for (const [tex, x, y, w, h, solid] of M.paint) { assert(existsSync(here(`assets/tiles/${tex}.png`)), tex); if (solid) solids.push([x * T, y * T, w * T, h * T]); }
  assert(existsSync(here(`assets/tiles/${M.ground}.png`)) && existsSync(here(`assets/tiles/battle_${M.battle}.png`)), mid);
  for (const [key, x, y] of M.objects) { const st = STAMPS[key]; assert(st, key); if (st.foot) solids.push([x * T + st.foot[0], y * T + st.foot[1], st.foot[2], st.foot[3]]); }
  const feet = (tx, ty) => [tx * T + 16, ty * T + 28];
  for (const n of M.npcs || []) { assert(cast[n.id], n.id); assert(TALK[n.talk], n.talk); const [x, y] = feet(n.x, n.y); solids.push([x - 12, y - 12, 24, 14]); }
  if (M.boss) { assert(ENEMIES[M.boss.enemy]); const [x, y] = feet(M.boss.x, M.boss.y); solids.push([x - 24, y - 16, 48, 16]); }
  for (const e of (M.encounters || []).flat()) assert(ENEMIES[e], e);
  // tile (tx,ty) is walkable when the hero's feet box at its centre touches nothing solid
  const open = (tx, ty) => tx >= 0 && ty >= 0 && tx < M.w && ty < M.h &&
    !solids.some(([sx, sy, sw, sh]) => { const [x, y] = feet(tx, ty); return x - 9 < sx + sw && x + 9 > sx && y - 8 < sy + sh && y + 2 > sy; });
  opens[mid] = open;
  assert(open(...M.spawn), `${mid}: spawn is blocked`);
  const seen = new Set([M.spawn.join()]), q = [M.spawn];
  while (q.length) { const [x, y] = q.shift(); for (const [a, b] of [[x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]]) if (open(a, b) && !seen.has(`${a},${b}`)) { seen.add(`${a},${b}`); q.push([a, b]); } }
  const reach = (tx, ty, what) => assert([[tx, ty], [tx + 1, ty], [tx - 1, ty], [tx, ty + 1], [tx, ty - 1]].some(([a, b]) => seen.has(`${a},${b}`)), `${mid}: cannot reach ${what} at ${tx},${ty}`);
  for (const z of M.zones || []) {
    assert(!z.go || MAPS[z.go.map], `${mid}: zone to unknown map`);
    let any = false; for (let x = z.x; x < z.x + z.w; x++) for (let y = z.y; y < z.y + z.h; y++) any ||= seen.has(`${x},${y}`);
    assert(any, `${mid}: cannot reach zone at ${z.x},${z.y}`);
    if (z.go) { const M2 = MAPS[z.go.map]; assert(z.go.x < M2.w && z.go.y < M2.h, "arrival inside the map"); }
  }
  for (const n of M.npcs || []) reach(n.x, n.y, n.id);
  for (const [key, x, y, opt] of M.objects) if (opt?.chest) { reach(x, y, opt.chest); reach(x, y + 1, opt.chest); }
  if (M.boss) reach(M.boss.x, M.boss.y, "the boss");
  seens[mid] = seen;
}
for (const [mid, M] of Object.entries(MAPS)) for (const z of M.zones || []) if (z.go) assert(opens[z.go.map](z.go.x, z.go.y), `${mid}: arrival in ${z.go.map} at ${z.go.x},${z.go.y} is blocked`);

// side quests: every id in the quest world exists in the game, and the written quests only use those ids
const npcQids = Object.values(MAPS).flatMap(M => (M.npcs || []).map(n => n.qid)).filter(Boolean);
for (const n of QUEST_WORLD.npcs) { assert(npcQids.includes(n.id), `quest NPC ${n.id} is on no map`); assert(PERSONAS[n.id], `no persona for ${n.id}`); }
for (const l of QUEST_WORLD.locations) assert(Object.values(REGIONS).flat().some(r => r[0] === l.id), `no region for ${l.id}`);
for (const it of QUEST_WORLD.items) {
  const [m, x, y] = ITEM_SPOTS[it.id] || []; assert(MAPS[m], `no spot for ${it.id}`);
  assert(seens[m].has(`${x},${y}`), `${it.id} at ${m} ${x},${y} cannot be reached`);
}
for (const q of FALLBACK_QUESTS) assert(questFits(q, QUEST_WORLD), q.title);
assert(!questFits({ steps: [{ objective: "fetch", target_id: "sword" }] }, QUEST_WORLD), "unknown items are rejected");
const tidy = tidyQuest({ title: "The tram_token", summary: "Find the lost_letter 冒险", story_summary: "", steps: [{ objective: "fetch", target_id: "tram_token", description: "Get the tram_token." }] }, SHORT_NAMES);
assert.equal(tidy.title, "The tram token"); assert.equal(tidy.summary, "Find the lost letter"); assert.equal(tidy.steps[0].target_id, "tram_token", "ids stay ids");
const st = { q: FALLBACK_QUESTS[1], step: 0 };
assert.equal(questStep(st, "fetch", "tram_token"), null, "steps happen in order");
assert.equal(questStep(st, "explore", "undercroft"), "step");
assert.equal(questStep(st, "fetch", "tram_token"), "step");
assert.equal(questStep(st, "talk_to", "ines"), "done");
const save = newGame("lead_m"); const pay = payQuest(save, FALLBACK_QUESTS[1]);
assert.equal(save.gold, 60 + pay.gold); assert.equal(save.items.potion, 4); assert.equal(save.questsDone, 1); assert(save.story.includes("tram token"));
console.log("ok");
