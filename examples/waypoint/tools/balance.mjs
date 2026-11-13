// node tools/balance.mjs: how often a party wins the story's fights, using the game's own damage and gauge rules.
// Two players are simulated: "smart" (spells, heals and potions when they help) and "casual" (only Fight, a potion when
// someone is below 35%). The enemy numbers in src/rules.js were tuned with this: a smart party should win the fights
// of its act at the level it usually has (about L3-L5 for the relays, L5-L6 for the Director), a casual one a level or
// two later.
import { newHero, damage, atbFill, ENEMIES, SKILLS, HEROES } from "../src/rules.js";

let POLICY = "smart";
function fight(lvl, foeIds, potions = 3, ether = 1, rand = Math.random) {
  const party = [newHero("lead_m", lvl), newHero("lead_f", lvl)].map(h => ({ h, atb: rand() * 60 }));
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
  for (let i = 0; i < N; i++) { const r = fight(lvl, foes, opts.potions ?? 3, opts.ether ?? 1); if (r.won) { w++; left += r.left; } secs += r.secs; }
  console.log(`${label.padEnd(34)} L${lvl}  win ${String(Math.round((100 * w) / N)).padStart(3)}%  hp left ${w ? Math.round((100 * left) / w) : 0}%  ~${Math.round(secs / N)}s`);
}

console.log("-- Warden (Act I)");
for (const l of [2, 3, 4]) report("The Warden", l, ["minotaur_mage"]);
console.log("-- Relay guards (Act II): the party is about L3 for the first relay, L4 for the second, L5 for the third");
for (const l of [3, 4, 5]) report("Guard + 2 drones", l, ["relay_guard", "relay_drone", "relay_drone"]);
console.log("-- Spire encounters (Act III), arriving at L5");
for (const l of [5, 6]) { report("2 guards", l, ["spire_guard", "spire_guard"]); report("wraith + drone", l, ["wraith", "spire_drone"]); report("3 drones", l, ["spire_drone", "spire_drone", "spire_drone"]); }
console.log("-- The Director");
for (const l of [5, 6, 7, 8]) report("The Director (3 potions, 1 ether)", l, ["director"]);
report("The Director (full supplies)", 6, ["director"], { potions: 8, ether: 3 });

POLICY = "casual";
console.log("== casual player: Fight only, potions below 35%");
for (const l of [3, 4, 5, 6]) report("Guard + 2 drones", l, ["relay_guard", "relay_drone", "relay_drone"]);
for (const l of [2, 3, 4]) report("The Warden", l, ["minotaur_mage"]);
for (const l of [5, 6, 7]) report("2 spire guards", l, ["spire_guard", "spire_guard"]);
for (const l of [6, 7, 8, 9]) report("The Director", l, ["director"]);
