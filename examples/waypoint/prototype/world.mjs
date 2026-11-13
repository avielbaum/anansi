// Waypoint's world builder: turns a real destination (and what the model knows about it) into a cast, a quest world
// and a seeded map. Pure functions, no DOM, so check.mjs can test them in Node.

export const W = 20, H = 12;
export const SOLID = new Set(["#", "B", "T", "~"]);
export const AGENT = { id: "agent", name: "Agent Kessler", role: "Directorate handler" };

export function hash(s) { let h = 2166136261; for (const c of s) h = Math.imul(h ^ c.codePointAt(0), 16777619); return h >>> 0; }
export function rng(seed) { // mulberry32
  return () => { seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t ^= t + Math.imul(t ^ (t >>> 7), 61 | t); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

// The player's destination goes into prompts: keep it one short line of plain text.
export const cleanDest = s => String(s).replace(/[\u0000-\u001f<>{}\[\]`|]/g, " ").replace(/\s+/g, " ").trim().slice(0, 50);
const clip = s => (/\p{L}/u.test(s) ? s.replace(/[*_#"]/g, "").replace(/\s+/g, " ").trim().slice(0, 40) : ""); // "..." is not a place

export const atlasPrompt = dest =>
  `List real things a visitor finds in ${dest}. Answer in exactly four lines like this example for Lisbon:
` +
  `PLACES: Alfama | Belém Tower | LX Factory
PEOPLE: Joana (fado singer) | Rui (tram driver) | Inês (pastry baker)
` +
  `ITEMS: pastel de nata | azulejo tile | sardine tin
VIBE: Steep sunny hills, yellow trams and sad songs at night.

Now ${dest}:`;

// Labeled lines when the model follows the format; otherwise the first lines in order (places, people, items, vibe).
export function parseAtlas(text) {
  const a = { places: [], people: [], items: [], vibe: "" };
  const lines = String(text).split("\n").map(l => l.replace(/[*_#`]/g, "").trim()).filter(Boolean);
  const keys = { PLACE: "places", PERSON: "people", PEOPLE: "people", ITEM: "items", VIBE: "vibe" };
  const LABEL = /^[-\d.)\s]*(PLACES?|PERSONS?|PEOPLE|ITEMS?|VIBE)\s*[:\-]\s*(.+)$/i, labeled = lines.some(l => LABEL.test(l));
  let pos = 0;
  for (const line of lines) {
    const m = line.match(LABEL);
    if (!m && labeled) continue; // chatter around a labeled answer
    const key = m ? keys[m[1].toUpperCase().replace(/S$/, "")] || keys[m[1].toUpperCase()] : ["places", "people", "items", "vibe"][pos++];
    if (!key) break;
    const v = (m ? m[2] : line.replace(/^[^:|]{1,40}:\s*/, "")).trim();
    if (key === "vibe") { a.vibe ||= v.slice(0, 160); continue; }
    for (const part of v.split(/\s*\|\s*|\s*;\s*/)) {
      if (key !== "people") { if (clip(part)) a[key].push(clip(part)); continue; }
      const pm = part.match(/^([^(,]+?)\s*(?:\(([^)]+)\)|,\s*(.+)|\s+[–-]\s+(.+))?$/);
      const name = clip(pm?.[1] || "").split(" ")[0];
      if (name) a.people.push({ name, role: clip(pm[2] || pm[3] || pm[4] || "local") });
    }
  }
  return a;
}

// Pads a thin or failed atlas so every destination has 3 places, 3 people and 3 items.
export function buildWorld(dest, atlas) {
  const gen = {
    places: [`the old quarter of ${dest}`, `${dest} central station`, `the waterfront of ${dest}`],
    people: [{ name: "Nia", role: "café owner" }, { name: "Marco", role: "taxi driver" }, { name: "Iris", role: "street medic" }],
    items: ["a hand-drawn city map", "a famous local snack", "an old transit token"],
  };
  const pick = (got, fill, key) => [...new Map([...got, ...fill].map(e => [key(e).toLowerCase(), e])).values()].slice(0, 3);
  const places = pick(atlas.places.filter(Boolean), gen.places, e => e);
  const people = pick(atlas.people, gen.people, e => e.name);
  const items = pick(atlas.items.filter(Boolean), gen.items, e => e);
  return {
    dest, vibe: atlas.vibe || `You blink into ${dest}. Nobody saw you arrive. Probably.`,
    world: {
      npcs: [...people.map((p, i) => ({ id: "p" + i, name: p.name, role: p.role })), AGENT],
      locations: places.map((n, i) => ({ id: "l" + i, name: n })),
      items: items.map((n, i) => ({ id: "i" + i, name: n })),
    },
  };
}

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
