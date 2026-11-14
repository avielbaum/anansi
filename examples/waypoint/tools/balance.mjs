// node tools/balance.mjs: how often a party wins the story's fights, using the game's own damage and gauge rules.
// Two players are simulated: "smart" (spells, heals and potions when they help) and "casual" (only Fight, a potion when
// someone is below 35%). The enemy numbers in src/rules.js were tuned with this: a smart party should win the fights
// of its act at the level it usually has (about L3-L5 for the relays, L5-L6 for the Director), a casual one a level or
// two later.
import { newHero, kit, START_GEAR, damage, atbFill, ENEMIES, SKILLS, HEROES } from "../src/rules.js";

// The gear a party usually has at each point of the story: the starting gear; the shop's and the Warden's by the relays;
// the Spire's chests and relay salvage by the Director.
const GEAR = {
  start: START_GEAR,
  act2: { lead_m: ["steel_blade", "leather_vest", "quick_boots"], lead_f: ["crystal_tome", "leather_vest", "brass_charm"] },
  act3: { lead_m: ["rift_edge", "plated_jacket", "vital_pendant"], lead_f: ["moon_scepter", "plated_jacket", "vital_pendant"] },
};
const mk = (id, lvl, gear) => { const h = newHero(id, lvl); kit(h, GEAR[gear][id]); return h; };

let POLICY = "smart";
function fight(lvl, foeIds, potions = 3, ether = 1, rand = Math.random, gear = "start", guest = null) {
  // a freed jumper (Act III, between sites) fights as a third member at the party's level, without equipment
  const party = [mk("lead_m", lvl, gear), mk("lead_f", lvl, gear), ...(guest ? [newHero(guest, lvl)] : [])].map(h => ({ h, atb: rand() * 60 }));
  const foes = foeIds.map(id => ({ ...ENEMIES[id], id, maxhp: ENEMIES[id].hp, atb: rand() * 60, turns: 0 }));
  const alive = a => a.filter(x => (x.h ? x.h.hp : x.hp) > 0);
  let t = 0, items = { potion: potions, ether };
  while (alive(party).length && alive(foes).length && t < 600_000) {
    t += 50;
    for (const p of alive(party)) p.atb = Math.min(100, p.atb + atbFill(p.h.spd, 50));
    for (const f of alive(foes)) f.atb = Math.min(100, f.atb + atbFill(f.spd, 50));
    for (const p of alive(party)) {
      if (p.atb < 100 || !alive(foes).length) continue;
      const h = p.h, weak = alive(party).find(q => q.h.hp < q.h.maxhp * 0.4);
      const foe = alive(foes).sort((a, b) => a.hp - b.hp)[0];
      if (POLICY === "casual") { if (weak && items.potion && q35(party)) { items.potion--; weak.h.hp = Math.min(weak.h.maxhp, weak.h.hp + 40); } else foe.hp -= damage(h.atk, foe.def, 1, rand); p.atb = 0; continue; }
      if (HEROES[h.id].guest) { // heal if hurt, else the area spell against a crowd, else the best single-target skill, else Fight
        const sk = HEROES[h.id].skills.map(k => SKILLS[k]).filter(k => k.mp <= h.mp);
        const heal = sk.find(k => k.kind === "heal"), area = sk.find(k => k.target === "enemies"), one = sk.filter(k => k.target === "enemy").sort((a, b) => b.power - a.power)[0];
        if (weak && heal) { const a = Math.min(weak.h.maxhp - weak.h.hp, heal.power + h.mag); weak.h.hp += a; h.mp -= heal.mp; }
        else if (area && alive(foes).length >= 2) { h.mp -= area.mp; for (const f of alive(foes)) f.hp -= damage(h.mag, Math.round(f.def * 0.6), area.power, rand); }
        else if (one) { h.mp -= one.mp; foe.hp -= one.kind === "phys" ? damage(h.atk, foe.def, one.power, rand) : damage(h.mag, Math.round(foe.def * 0.6), one.power, rand); }
        else foe.hp -= damage(h.atk, foe.def, 1, rand);
        p.atb = 0; continue;
      }
      if (weak && h.id === "lead_f" && h.mp >= 5) { const a = Math.min(weak.h.maxhp - weak.h.hp, SKILLS.mend.power + h.mag); weak.h.hp += a; h.mp -= 5; }
      else if (weak && items.potion) { items.potion--; weak.h.hp = Math.min(weak.h.maxhp, weak.h.hp + 40); }
      else if (h.mp < 4 && items.ether) { items.ether--; h.mp = Math.min(h.maxmp, h.mp + 15); }
      else if (h.id === "lead_m" && alive(foes).length >= 3 && h.mp >= 8) { h.mp -= 8; for (const f of alive(foes)) f.hp -= damage(h.mag, Math.round(f.def * 0.6), 1.1, rand); }
      else if (h.id === "lead_m" && h.mp >= 4) { h.mp -= 4; foe.hp -= damage(h.atk, foe.def, 2, rand); }
      else if (h.id === "lead_f" && h.mp >= 5) { h.mp -= 5; foe.hp -= damage(h.mag, Math.round(foe.def * 0.6), 1.8, rand); }
      else foe.hp -= damage(h.atk, foe.def, 1, rand);
      p.atb = 0;
    }
    for (const f of alive(foes)) {
      if (f.atb < 100) continue;
      f.atb = 0; f.turns++;
      const raged = f.rage && f.hp <= f.maxhp * f.rage.at, every = raged ? f.rage.waveEvery : f.waveEvery || 3, atk = raged ? f.rage.atk : f.atk;
      const wave = f.boss && f.turns % every === 0, hex = !wave && f.magic && rand() < 0.5, live = alive(party);
      if (!live.length) break;
      for (const p of wave ? live : [live[Math.floor(rand() * live.length)]])
        p.h.hp = Math.max(0, p.h.hp - (wave ? damage(f.mag, p.h.def / 2, 0.9, rand) : hex ? damage(f.mag, p.h.def / 2, 1.2, rand) : damage(atk, p.h.def, 1, rand)));
    }
  }
  const won = alive(foes).length === 0, left = party.reduce((a, p) => a + p.h.hp, 0) / party.reduce((a, p) => a + p.h.maxhp, 0);
  return { won, left, secs: t / 1000 };
}

const q35 = party => party.some(q => q.h.hp > 0 && q.h.hp < q.h.maxhp * 0.35);
function report(label, lvl, foes, opts = {}) {
  const N = 400; let w = 0, left = 0, secs = 0;
  for (let i = 0; i < N; i++) { const r = fight(lvl, foes, opts.potions ?? 3, opts.ether ?? 1, Math.random, opts.gear || "start", opts.guest); if (r.won) { w++; left += r.left; } secs += r.secs; }
  console.log(`${label.padEnd(34)} L${lvl} ${(opts.gear || "start").padEnd(5)} ${(opts.guest || "-").padEnd(5)} win ${String(Math.round((100 * w) / N)).padStart(3)}%  hp left ${w ? Math.round((100 * left) / w) : 0}%  ~${Math.round(secs / N)}s`);
}

const REPORT = [
  ["Act I: the Warden (starting gear)", [2, 3, 4], ["minotaur_mage"], "start"],
  ["Act II: guard + 2 drones (steel/tome, vest)", [3, 4, 5], ["relay_guard", "relay_drone", "relay_drone"], "act2"],
  ["Act III: site guard + drones", [5, 6, 7], ["site_guard", "site_drone", "site_drone"], "act2"],
  ["Act III: Lantern Warden", [5, 6, 7], ["lantern_warden"], "act2"],
  ["Act III: Clock Sentinel", [5, 6, 7], ["clock_sentinel"], "act2"],
  ["Act III: Sand Colossus", [5, 6, 7], ["sand_colossus"], "act2"],
  ["Act III: Jungle Hydra", [5, 6, 7], ["hydra"], "act2"],
  ["Act III: Kessler's Walker (after 2 sites)", [6, 7, 8], ["kessler"], "act2"],
  ["Act IV: Vesper", [7, 8, 9], ["vesper"], "act3"],
  ["Act V: 2 spire guards (Spire gear)", [7, 8, 9], ["spire_guard", "spire_guard"], "act3"],
  ["Act V: the Director (Spire gear)", [7, 8, 9, 10], ["director"], "act3"],
];
for (const policy of ["smart", "casual"]) {
  POLICY = policy;
  console.log(`== ${policy === "smart" ? "skilled player: spells, heals and potions when they help" : "casual player: Fight only, a potion below 35%"}`);
  for (const [label, levels, foes, gear] of REPORT) for (const l of levels) report(label, l, foes, { gear });
  // Act III fights after the first site, with each freed jumper along (Vesper's and the Director's fights have none: they leave first)
  for (const [label, levels, foes, gear] of REPORT.filter(r => /Act III: (?!site)/.test(r[0]))) for (const guest of ["sora", "ilse", "oluwa"]) report(label, levels[1], foes, { gear, guest });
}
