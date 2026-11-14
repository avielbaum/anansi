// node check.mjs: rules, data and maps agree; every exit, chest, NPC and boss can be reached on foot.
import assert from "node:assert";
import { readFileSync, existsSync } from "node:fs";
import { damage, gainXp, newHero, newGame, atbFill, useItem, xpToNext, ENEMIES, HEROES, SKILLS, questStep, payQuest, questFits, tidyQuest, canGift, markGift, resetGifts } from "./src/rules.js";
import { SITE_GEAR, EQUIP, START_GEAR, SHOP_GEAR, SHOP_GEAR2, WARDEN_GEAR, RELAY_GEAR, SLOTS, kit, addGear, equip, unequip, preview, canEquip } from "./src/rules.js";
import { upgrade } from "./src/state.js";
import { MAPS, STAMPS, TALK, QUEST_WORLD, REGIONS, ITEM_SPOTS, PERSONAS, FALLBACK_QUESTS, SHORT_NAMES } from "./src/data.js";
import { pages } from "./src/ui.js";
import { SITE_BEATS, completeSite, banter, newPlot, destroyRelay, objective, situation, BEATS, ENDINGS, ACTS, RELAYS_NEEDED, epilogueFallback } from "./src/story.js";
import { genCity, walkable, LOCALS } from "./src/city.js";
import { REGIONS as WORLD, REGION_IDS, regionOf, anchorOf } from "./src/regions.js";
import { hash, parseAtlas, parseClimate, cityPrompt, CLIMATES, suggest, DESTINATIONS } from "./src/atlas.js";

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
  if (M.boss) { reach(M.boss.x, M.boss.y, "the boss"); assert(BEATS.bossIntro[M.boss.flag] && M.boss.name, `${mid}: the boss has no intro or name`); }
  for (const pd of M.pads || []) reach(pd.x, pd.y, "a recovery pad");
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
// Teleport's suggestions: never somewhere already visited (any capitalisation), five of them, a different handful as you travel
const s0 = suggest([]); assert.equal(s0.length, 5); assert.equal(new Set(s0).size, 5);
assert(!suggest(["kyoto", "MARRAKECH"], 16).some(d => ["Kyoto", "Marrakech"].includes(d)), "visited places are not suggested");
assert.notDeepEqual(suggest([], 5, 0), suggest([], 5, 3), "the list moves on");
assert.equal(suggest(DESTINATIONS.slice(1), 5).length, 1, "a small pool gives fewer, not repeats");
assert.equal(suggest(DESTINATIONS).length, 0);
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
  const rl = M.relay; assert(rl, `${dest}: no relay`);
  assert([[rl.x, rl.y], [rl.x + 1, rl.y], [rl.x - 1, rl.y], [rl.x, rl.y + 1], [rl.x, rl.y - 1]].some(([a, b]) => seen.has(`${a},${b}`)), `${dest}: cannot reach the relay`);
  assert(![...M.npcs, ...Object.values(area.itemSpots).map(([, x, y]) => ({ x, y }))].some(o => o.x === rl.x && o.y === rl.y), `${dest}: the relay shares a spot`);
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
// ---- the story: acts, objectives, every beat, and the enemies they use -------------------------------------------------------
const plot = newPlot();
assert.equal(plot.act, 1); assert(objective(plot).includes("Warden"));
plot.act = 2;
assert(objective(plot).includes(`0 of ${RELAYS_NEEDED}`));
assert.deepEqual(destroyRelay(plot, "city:Kyoto"), { count: 1, last: false });
assert.deepEqual(destroyRelay(plot, "city:Kyoto"), { count: 1, last: false }, "one relay per city");
destroyRelay(plot, "city:Cairo");
assert.deepEqual(destroyRelay(plot, "city:Oslo"), { count: 3, last: true });
assert(situation(plot, false).includes("3 of 3") && situation(newPlot(), true).includes("Warden") && situation(newPlot(), false) === "");
plot.act = 3; assert(objective(plot).includes("Rift Sites") && objective(plot).includes("0 of 4"));
assert.deepEqual(completeSite(plot, "pacific"), { count: 1, fresh: true, rivalNow: false, last: false });
assert.deepEqual(completeSite(plot, "pacific"), { count: 1, fresh: false, rivalNow: false, last: false }, "one jumper per region");
assert(completeSite(plot, "europe").rivalNow, "Kessler ambushes after the second site"); plot.rival = true;
completeSite(plot, "sahara"); assert(completeSite(plot, "americas").last);
plot.act = 4; assert(objective(plot).includes("Vesper"));
plot.act = 5; assert(objective(plot).includes("Director")); plot.ending = "burn"; assert(objective(plot).includes("finished"));
assert.equal(ACTS.length, 6);
const speakers = new Set(["", "LEAD", "MATE", "Agent Kessler", "The Director", "Vesper", ...REGION_IDS.map(r => WORLD[r].ally)]);
const lines = [...BEATS.wardenWon, ...BEATS.spireArrive, ...BEATS.directorWon, ...BEATS.bossIntro.director, ...BEATS.relayFound("X"), ...BEATS.relayDown(1, "X"), ...BEATS.relayDown(3, "X"), ...Object.values(BEATS.endings).flat(), ...BEATS.kesslerAmbush, ...BEATS.kesslerWon, ...BEATS.allFree, ...BEATS.vesperWon, ...BEATS.bossIntro.kessler.map(l => ["", l]), ...BEATS.bossIntro.vesper.map(l => ["", l]), ...Object.values(SITE_BEATS).flatMap(b => [...b.won, ...b.boss.map(l => ["", l]), ["", b.door]])];
for (const l of lines) { assert(Array.isArray(l) && speakers.has(l[0]) && l[1].length > 5, JSON.stringify(l)); assert(l[1].length < 330, "a line must fit three pages of the dialogue box: " + l[1].slice(0, 30)); }
assert(BEATS.bossIntro.warden.every(l => typeof l === "string"));
assert.deepEqual(Object.keys(BEATS.endings).sort(), Object.keys(ENDINGS).sort(), "each ending has its words");
assert(epilogueFallback("burn", ["Cairo", "Kyoto"]).includes("Cairo") && epilogueFallback("keep", []).length > 30);
assert(BEATS.relayDown(3, "X").some(l => l[1].includes("RIFT SITES")), "the third relay leads to the Rift Sites");
// a save from before the story: after the Warden it starts in Act II, before it in Act I
assert.equal(upgrade({ v: 1, map: "town", flags: { warden: true } }).plot.act, 2);
assert.equal(upgrade({ v: 1, map: "town", flags: {} }).plot.act, 1);
assert.equal(newGame("lead_f").plot.act, 1);
// every enemy has a picture and sane numbers; the Director has a second phase
for (const [id, e] of Object.entries(ENEMIES)) {
  assert(existsSync(here(`assets/enemies/${e.sprite || id}.png`)), `${id}: no picture`);
  assert(e.hp > 0 && e.def >= 0 && e.spd > 0 && e.name && e.xp >= 0 && e.gold >= 0, id);
}
assert(ENEMIES.director.boss && ENEMIES.director.rage.atk > ENEMIES.director.atk && ENEMIES.director.rage.waveEvery < ENEMIES.director.waveEvery);
assert(MAPS.spire.pads.length >= 2 && MAPS.spire.boss.enemy === "director" && MAPS.spire.arrival === "spireArrive" && BEATS[MAPS.spire.arrival]);
// ---- sound: everything the code asks for is in the manifest, every file exists, and no asset sits unused --------------------
import { statSync } from "node:fs";
const audio = JSON.parse(readFileSync(here("assets/audio/manifest.json")));
const srcText = ["audio", "battle", "city", "data", "ending", "field", "main", "menu", "rules", "ui"].map(f => readFileSync(here(`src/${f}.js`), "utf8")).join("\n");
const quoted = name => { // every "word" inside the calls name(...)
  const out = new Set();
  for (let i = srcText.indexOf(name + "("); i >= 0; i = srcText.indexOf(name + "(", i + 1)) {
    let d = 0, j = i + name.length;
    for (; j < srcText.length; j++) { if (srcText[j] === "(") d++; else if (srcText[j] === ")" && --d === 0) break; }
    for (const m of srcText.slice(i, j).matchAll(/"(\w+)"/g)) out.add(m[1]);
  }
  return out;
};
const sfxUsed = new Set([...quoted("sfx"), ...[...srcText.matchAll(/sound: "(\w+)"/g)].map(m => m[1]), // a skill's sound
  ...[...srcText.matchAll(/goTo\(\{[^}]*\}, "(\w+)"\)/g)].map(m => m[1]), ...[...srcText.matchAll(/sound = "(\w+)"/g)].map(m => m[1])]); // the sound of changing map
const musicUsed = new Set([...quoted("music"), ...quoted("musicPush"), ...[...srcText.matchAll(/music: "(\w+)"/g)].map(m => m[1]),
  ...[...srcText.match(/CITY_MUSIC = \{([^}]*)\}/)[1].matchAll(/"(\w+)"/g)].map(m => m[1])]);
for (const k of sfxUsed) assert(audio.sfx[k], `the code plays the effect "${k}", which is not in the manifest`);
for (const k of musicUsed) assert(audio.music[k], `the code plays the track "${k}", which is not in the manifest`);
for (const k of Object.keys(audio.sfx)) assert(sfxUsed.has(k), `the effect "${k}" is never played; remove it from tools/audio.json`);
for (const k of Object.keys(audio.music)) assert(musicUsed.has(k), `the track "${k}" is never played; remove it from tools/audio.json`);
let audioBytes = 0;
for (const v of [...Object.values(audio.sfx), ...Object.values(audio.music)]) { assert(existsSync(here(`assets/audio/${v.file}`)), v.file); audioBytes += statSync(here(`assets/audio/${v.file}`)).size; }
for (const v of Object.values(audio.music)) assert(v.gain > 0 && v.gain <= 1, "music gains bring tracks down to the quietest: at most 1");
assert(audioBytes < 8e6, `audio is ${(audioBytes / 1e6).toFixed(1)} MB; keep the repo small (re-encode or drop tracks)`);
for (const M of Object.values(MAPS)) assert(audio.music[M.music] && (!M.boss || audio.music[M.boss.music]), `${M.name}: missing music`);
for (const c of CLIMATES) assert(audio.music[genCity("Testville", parseAtlas(atlasText), c).map.music], `no music for the ${c} climate`);
assert(existsSync(here("assets/CREDITS_AUDIO.csv")), "run python tools/build_audio.py");
for (const k of Object.keys(SKILLS)) assert(existsSync(here(`assets/icons/skill_${k}.png`)), `${k}: no icon`);
for (const s of Object.values(SKILLS)) assert(s.sound && audio.sfx[s.sound], "every skill has a sound");

// cities look different from each other
{
  const names = ["Kyoto", "Lisbon", "Cairo", "Reykjavik", "Lima", "Oslo", "Hanoi", "Perth", "Nairobi", "Quito", "Dubai", "Tromso"];
  const looks = new Set();
  for (const n of names) for (const c of CLIMATES) {
    const M = genCity(n, parseAtlas(atlasText), c).map;
    assert(existsSync(here(`assets/tiles/battle_${M.battle}.png`)), `${n}: no backdrop ${M.battle}`);
    looks.add(M.battle);
  }
  assert(looks.size >= 10, `only ${looks.size} different battle backdrops`);
  const M = genCity("Kyoto", parseAtlas(atlasText), "temperate").map;
  assert(new Set(M.objects.filter(o => o[0].startsWith("house")).map(o => o[0])).size > 1, "houses differ in colour");
  const styles = new Set();
  for (let i = 0; i < 60; i++) { const c = genCity("Town" + i, parseAtlas(atlasText), CLIMATES[i % 4]).map; styles.add(c.style); for (const o of c.objects) assert(existsSync(here(`assets/tiles/${o[0]}.png`)) && STAMPS[o[0]], `${c.name}: no picture or stamp for ${o[0]}`); for (const [t] of c.paint) assert(existsSync(here(`assets/tiles/${t}.png`)), t); }
  assert(styles.has("harbor") && styles.has("river") && styles.has("street"), `layout styles seen: ${[...styles]}`);
}
// regions and the world map
for (const id of REGION_IDS) {
  const R = WORLD[id];
  assert(R.places.includes(R.anchor) && regionOf(R.anchor) === id && anchorOf(R.anchor) === id && R.ally, id);
  const M = genCity(R.anchor, parseAtlas(atlasText), "temperate").map;
  assert(M.rift?.region === id, `${R.anchor} has no Rift Door`);
  assert(MAPS[`site:${id}`] && BEATS.bossIntro[`site_${id}`] && SITE_GEAR[id] && SITE_BEATS[id].won.length, `${id}: the site is incomplete`);
  assert(genCity("Somewhere", parseAtlas(atlasText), "temperate").map.rift === null);
}
assert.equal(regionOf("kyōto"), "pacific"); assert.equal(regionOf("Nowhereville"), null); assert.equal(anchorOf("Cairo, Egypt"), "sahara");
assert(MAPS["site:gate"] && BEATS.bossIntro.vesper, "the Rift Gate");
const allPlaces = REGION_IDS.flatMap(id => WORLD[id].places.map(p => p.toLowerCase())); assert.equal(new Set(allPlaces).size, allPlaces.length, "a place is in two regions");
// a save from before the Rift Sites: the Spire was Act III
assert.equal(upgrade({ v: 1, map: "town", flags: {}, plot: { act: 3, relays: [], spire: true, ending: null } }).plot.act, 5);
// companion banter
for (const c of CLIMATES) for (const st of ["street", "harbor", "river"]) for (let i = 0; i < 6; i++) assert(banter(c, st, hash("x" + i)).length > 10, `${c}/${st}: no banter`);
// wildlife
for (const c of CLIMATES) {
  const enc = genCity("Wildville", parseAtlas(atlasText), c).map.encounters;
  assert(enc.length >= 5 && enc.some(f => ENEMIES[f[0]].tint || !["spider_bot", "drone_tank", "bat", "slime", "snake"].includes(f[0])), `${c}: no local wildlife`);
}
for (const [id, e] of Object.entries(ENEMIES)) assert(existsSync(here(`assets/enemies/${e.sprite || id}.png`)), `${id}: no picture`);
// equipment
{
  const g = newGame("lead_m"), kai = g.party[0], mira = g.party[1];
  assert(kai.eq.weapon === "training_blade" && mira.eq.weapon === "training_rod", "each lead starts with their own weapon");
  const before = { ...kai };
  addGear(g, "rift_edge"); equip(g, kai, "rift_edge");
  assert.equal(kai.atk, before.atk - EQUIP.training_blade.atk + EQUIP.rift_edge.atk);
  assert.equal(g.gear.training_blade, 1, "the old weapon goes back to the bag");
  assert(!canEquip(mira, "rift_edge") && canEquip(kai, "rift_edge"), "weapons are for one lead");
  unequip(g, kai, "weapon"); equip(g, kai, "training_blade");
  assert.deepEqual({ atk: kai.atk, def: kai.def, maxhp: kai.maxhp }, { atk: before.atk, def: before.def, maxhp: before.maxhp }, "equip and unequip round-trip");
  addGear(g, "brass_charm"); equip(g, kai, "brass_charm"); kai.hp = kai.maxhp; unequip(g, kai, "accessory");
  assert(kai.hp <= kai.maxhp, "hp is clamped when the maximum drops");
  addGear(g, "vital_pendant");
  assert.equal(preview(kai, "accessory", "vital_pendant").maxhp, kai.maxhp + EQUIP.vital_pendant.hp, "the preview shows the real result");
  const ids = new Set([...Object.values(START_GEAR).flat(), ...SHOP_GEAR, ...SHOP_GEAR2, ...WARDEN_GEAR, ...RELAY_GEAR, ...Object.values(SITE_GEAR)]);
  for (const M of Object.values(MAPS)) for (const e of M.things || M.objects || []) if (e[3]?.equip) ids.add(e[3].equip);
  for (const id of Object.keys(EQUIP)) { assert(ids.has(id), `${id} cannot be obtained`); assert(existsSync(here(`assets/icons/${id}.png`)), `${id}: no icon`); assert(SLOTS.includes(EQUIP[id].slot)); }
  for (const id of ids) assert(EQUIP[id], `unknown gear ${id}`);
  const old = newGame("lead_f"); delete old.gear; old.party.forEach(h => delete h.eq);
  upgrade(old); assert(old.gear && old.party.every(h => h.eq), "old saves get gear");
}

const save = newGame("lead_m"); const pay = payQuest(save, FALLBACK_QUESTS[1]);
assert.equal(save.gold, 60 + pay.gold); assert.equal(save.items.potion, 4); assert.equal(save.questsDone, 1); assert(save.story.includes("tram token"));
console.log("ok");
