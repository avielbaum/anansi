// Waypoint's world builder: turns a real destination (and what the model knows about it) into a cast, a quest world
// and a seeded map. Pure functions, no DOM, so check.mjs can test them in Node.

export const W = 20, H = 12;
export const SOLID = new Set(["#", "B", "T", "~"]);
import { AGENT, hash, rng, cleanDest, parseAtlas, buildWorld } from "../src/atlas.js";
export { AGENT, hash, rng, cleanDest, parseAtlas, buildWorld };

export const atlasPrompt = dest =>
  `List real things a visitor finds in ${dest}. Answer in exactly four lines like this example for Lisbon:
` +
  `PLACES: Alfama | Belém Tower | LX Factory
PEOPLE: Joana (fado singer) | Rui (tram driver) | Inês (pastry baker)
` +
  `ITEMS: pastel de nata | azulejo tile | sardine tin
VIBE: Steep sunny hills, yellow trams and sad songs at night.

Now ${dest}:`;


export function fallbackQuest({ dest, world }, chapter) {
  const [p, l, i] = [world.npcs[chapter % 3], world.locations[(chapter + 1) % 3], world.items[chapter % 3]];
  return {
    title: `${dest}: Out of Sight`, summary: `The Directorate has eyes in ${dest}. Find help and lose them.`, reward_tier: "medium",
    steps: [
      { objective: "talk_to", target_id: p.id, description: `Ask ${p.name} the ${p.role} for help.` },
      { objective: "explore", target_id: l.id, description: `Slip through ${l.name}.` },
      { objective: "fetch", target_id: i.id, description: `Find ${i.name} to cover your tracks.` },
    ],
    story_summary: `In ${dest}, the hero slipped the Directorate's net once more.`,
  };
}

// The map: three districts left to right (one per location), roads through each, obstacles seeded by the name.
export const zoneAt = x => (x <= 6 ? 0 : x <= 12 ? 1 : 2);
export function genMap(dest, world) {
  const r = rng(hash(dest.toLowerCase())), ri = n => Math.floor(r() * n);
  const g = Array.from({ length: H }, (_, y) => Array.from({ length: W }, (_, x) => (x === 0 || y === 0 || x === W - 1 || y === H - 1 ? "#" : ".")));
  const roadY = 4 + ri(4);
  for (let x = 1; x < W - 1; x++) g[roadY][x] = ",";
  for (const s of [1, 7, 13]) { const c = s + ri(5); for (let y = 1; y < H - 1; y++) g[y][c] = ","; }
  const water = r() * 0.15;
  for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++)
    if (g[y][x] === "." && r() < 0.24) { const k = r(); g[y][x] = k < water ? "~" : k < 0.65 ? "B" : "T"; }
  const start = { x: 1, y: roadY };
  const seen = new Set([start.x + "," + start.y]), q = [start];
  while (q.length) { const { x, y } = q.shift(); for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { const n = { x: x + dx, y: y + dy };
    if (!SOLID.has(g[n.y][n.x]) && !seen.has(n.x + "," + n.y)) { seen.add(n.x + "," + n.y); q.push(n); } } }
  const used = new Set([start.x + "," + start.y]);
  const spot = zone => {
    const all = [...seen].map(k => k.split(",").map(Number)).filter(([x, y]) => !used.has(x + "," + y) && g[y][x] === ".");
    const pool = all.filter(([x]) => zone === undefined || zoneAt(x) === zone);
    const [x, y] = (pool.length ? pool : all)[ri((pool.length ? pool : all).length)];
    used.add(x + "," + y); return { x, y };
  };
  const npcPos = {}, itemPos = {};
  world.npcs.forEach((n, i) => (npcPos[n.id] = spot(n.id === "agent" ? 1 + ri(2) : i)));
  world.items.forEach((it, i) => (itemPos[it.id] = spot((i + 1) % 3)));
  const hue = hash(dest) % 360;
  return { map: g.map(row => row.join("")), start, npcPos, itemPos, reachable: seen, hue };
}
