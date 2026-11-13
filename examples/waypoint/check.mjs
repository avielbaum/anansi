// node check.mjs: rules, data and maps agree; every exit, chest, NPC and boss can be reached on foot.
import assert from "node:assert";
import { readFileSync, existsSync } from "node:fs";
import { damage, gainXp, newHero, newGame, atbFill, useItem, xpToNext, ENEMIES, HEROES, SKILLS, questStep, payQuest, questFits, tidyQuest, canGift, markGift, resetGifts } from "./src/rules.js";
import { upgrade } from "./src/state.js";
import { MAPS, STAMPS, TALK, QUEST_WORLD, REGIONS, ITEM_SPOTS, PERSONAS, FALLBACK_QUESTS, SHORT_NAMES } from "./src/data.js";
import { pages } from "./src/ui.js";
import { genCity, walkable, LOCALS } from "./src/city.js";
import { parseAtlas, parseClimate, cityPrompt, CLIMATES } from "./src/atlas.js";

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
  for (const [tex] of M.paint) assert(existsSync(here(`assets/tiles/${tex}.png`)), tex);
  assert(existsSync(here(`assets/tiles/${M.ground}.png`)) && existsSync(here(`assets/tiles/battle_${M.battle}.png`)), mid);
  for (const [key] of M.objects) assert(STAMPS[key], key);
  for (const n of M.npcs || []) { assert(cast[n.id], n.id); assert(TALK[n.talk], n.talk); }
  if (M.boss) assert(ENEMIES[M.boss.enemy]);
  for (const e of (M.encounters || []).flat()) assert(ENEMIES[e], e);
  const { open, seen } = walkable(M); // tile (tx,ty) is walkable when the hero's feet box at its centre touches nothing solid
  opens[mid] = open;
  assert(open(...M.spawn), `${mid}: spawn is blocked`);
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
// the one-gift-per-NPC limit lives in the save: it survives a reload, and resets on rest or a finished quest
const gs = newGame("lead_m");
assert(canGift(gs, "home:ines")); markGift(gs, "home:ines");
assert(!canGift(gs, "home:ines")); assert(canGift(gs, "home:tobias"), "other NPCs are unaffected");
assert(!canGift(JSON.parse(JSON.stringify(gs)), "home:ines"), "a saved game remembers the gift");
resetGifts(gs); assert(canGift(gs, "home:ines"), "resting resets it");
markGift(gs, "home:ines"); payQuest(gs, FALLBACK_QUESTS[0]); assert(canGift(gs, "home:ines"), "a finished quest resets it");
// saves from before gifts, cities and quest areas existed still load
const old = upgrade({ v: 1, map: "town", pos: null, quest: { q: FALLBACK_QUESTS[0], step: 0 }, offer: FALLBACK_QUESTS[1], flags: {} });
assert.deepEqual([old.gifted, old.cities, old.quest.area, old.offer.area, old.offer.q.title], [{}, {}, "home", "home", FALLBACK_QUESTS[1].title]);
assert.equal(upgrade({ v: 1, map: "city:Nowhere", pos: { x: 1, y: 1 }, flags: {} }).map, "town", "a city with no saved data falls back to town");
// ---- generated cities: whatever the model says (or nothing), the town is complete, walkable and consistent ----------------
const atlasText = "PLACES: Fushimi Inari | Kinkaku-ji | Gion\nPEOPLE: Kiyomi (tea maker) | Akira (sushi chef) | Tada (calligrapher)\nITEMS: kaiseki | torii gate | matcha\nVIBE: Tranquil temples and lanterns.\nCLIMATE: snow";
assert.deepEqual(["desert", "cold and snowy", "Tropical", "temperate (one of desert, snow)", "", "warm"].map(c => parseClimate(`CLIMATE: ${c}`)), ["desert", "snow", "tropical", "temperate", "temperate", "temperate"]);
assert(CLIMATES.every(c => existsSync(here(`assets/tiles/${{ temperate: "grass", desert: "ground_sand", snow: "ground_snow", tropical: "ground_lush" }[c]}.png`))), "a ground texture per climate");
assert(cityPrompt("Lisbon").includes("CLIMATE") && cityPrompt("Kyoto").endsWith("Now Kyoto:"));
for (const id of LOCALS) assert(cast[id], `${id} is missing from the built sprites`);
const dests = ["Kyoto", "Marrakech", "Reykjavik", "Singapore", "Lima", "x", "Ulaanbaatar", "Cape Town", "Oslo", "Hanoi", "Buenos Aires", "Nairobi", "São Paulo", "Tromsø", "Yakutsk", "Dubai",
  ...Array.from({ length: 40 }, (_, i) => `City ${i * 7919}`)];
for (const [i, dest] of dests.entries()) {
  const climate = CLIMATES[i % 4], atlas = i === 5 ? parseAtlas("...") : parseAtlas(atlasText); // "x" gets the SDK's empty fallback
  const c = genCity(dest, atlas, climate), M = c.map, area = c.area;
  assert(c.ok, `${dest}: no valid layout`);
  assert.equal(JSON.stringify(genCity(dest, atlas, climate).map), JSON.stringify(M), `${dest}: the same city must always look the same`);
  for (const [tex] of M.paint) assert(existsSync(here(`assets/tiles/${tex}.png`)), tex);
  assert(existsSync(here(`assets/tiles/${M.ground}.png`)) && existsSync(here(`assets/tiles/battle_${M.battle}.png`)));
  for (const [key] of M.objects) assert(STAMPS[key], key);
  for (const e of M.encounters.flat()) assert(ENEMIES[e], e);
  const { open, seen } = walkable(M);
  assert(open(...M.spawn), `${dest}: spawn is blocked`);
  assert.equal(M.npcs.length, 4); assert.equal(new Set(M.npcs.map(n => n.id)).size, 4, `${dest}: two people share a sprite`);
  for (const n of M.npcs) {
    assert(cast[n.id], n.id); assert(area.personas[n.qid], `no persona for ${n.qid}`); assert(n.lines.length >= 3 && n.name);
    assert([[n.x, n.y], [n.x + 1, n.y], [n.x - 1, n.y], [n.x, n.y + 1], [n.x, n.y - 1]].some(([a, b]) => seen.has(`${a},${b}`)), `${dest}: cannot reach ${n.qid}`);
  }
  assert.deepEqual(area.world.npcs.map(n => n.id).sort(), M.npcs.map(n => n.qid).sort());
  for (const it of area.world.items) { const [m, x, y] = area.itemSpots[it.id]; assert.equal(m, area.key); assert(seen.has(`${x},${y}`), `${dest}: cannot reach ${it.id}`); }
  for (const l of area.world.locations) assert(area.regions[area.key].some(r => r[0] === l.id), `${dest}: no region for ${l.id}`);
  assert.equal(area.fallbackQuests.length, 3);
  for (const q of area.fallbackQuests) assert(questFits(q, area.world), `${dest}: ${q.title}`);
  assert(!/\b[pli]\d\b/.test(tidyQuest({ title: "t", summary: "Ask p0 at l1 for i2", story_summary: "", steps: [] }, area.names).summary), "city ids become names");
}
const save = newGame("lead_m"); const pay = payQuest(save, FALLBACK_QUESTS[1]);
assert.equal(save.gold, 60 + pay.gold); assert.equal(save.items.potion, 4); assert.equal(save.questsDone, 1); assert(save.story.includes("tram token"));
console.log("ok");
