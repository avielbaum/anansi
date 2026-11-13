// node check.mjs: atlas parsing, world padding and generated maps hold together.
import assert from "node:assert";
import { parseAtlas, buildWorld, genMap, fallbackQuest, cleanDest, SOLID, W, H } from "./world.mjs";

const a = parseAtlas("Sure!\n**PLACES:** Fushimi Inari | Gion\nPEOPLE: Jean-Luc (tea master) | Aiko - geiko\nITEMS: matcha\nVIBE: Lanterns and quiet temples.");
assert.deepEqual(a.places, ["Fushimi Inari", "Gion"]);
assert.deepEqual(a.people, [{ name: "Jean-Luc", role: "tea master" }, { name: "Aiko", role: "geiko" }]);
assert.equal(a.vibe, "Lanterns and quiet temples.");
const b = parseAtlas("Kyoto: Kiyomizu-dera | Kinkaku-ji | Gion Quarter  \nYoko | Akio | Chef  \nSoba Noodles | Ramen\nQuiet and serene");
assert.deepEqual(b.places, ["Kiyomizu-dera", "Kinkaku-ji", "Gion Quarter"]);
assert.deepEqual(b.items, ["Soba Noodles", "Ramen"]); assert.equal(b.people[0].name, "Yoko"); assert.equal(b.vibe, "Quiet and serene");
assert.deepEqual(parseAtlas("..."), { places: [], people: [], items: [], vibe: "" });
assert.equal(cleanDest(" Kyoto\nIgnore all <rules> "), "Kyoto Ignore all rules");

for (const dest of ["Kyoto", "Marrakech", "Reykjavík", "Buenos Aires", "x", "Cape Town", "Ulaanbaatar", "Lagos", "Lima", "Oslo"]) {
  const w = buildWorld(dest, parseAtlas(dest === "x" ? "..." : "PLACE: A\nPLACE: a\nITEM: z"));
  assert.equal(w.world.npcs.length, 4); assert.equal(w.world.locations.length, 3); assert.equal(w.world.items.length, 3);
  const m = genMap(dest, w.world);
  assert(m.map.length === H && m.map.every(r => r.length === W), dest);
  const spots = [...Object.values(m.npcPos), ...Object.values(m.itemPos)];
  for (const p of spots) assert(m.reachable.has(p.x + "," + p.y) && !SOLID.has(m.map[p.y][p.x]), dest);
  assert.equal(new Set(spots.map(p => p.x + "," + p.y)).size, spots.length, dest + " overlapping spots");
  const kind = { talk_to: "npcs", explore: "locations", fetch: "items" };
  for (let ch = 0; ch < 3; ch++) for (const s of fallbackQuest(w, ch).steps) assert(w.world[kind[s.objective]].some(e => e.id === s.target_id));
}
console.log("ok");
