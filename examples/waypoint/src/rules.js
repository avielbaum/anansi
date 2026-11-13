// Game rules with no Phaser in them, so check.mjs can test them in Node.

export const ITEMS = {
  potion: { name: "Potion", price: 20, hp: 40, desc: "Restores 40 HP to one ally." },
  ether: { name: "Ether", price: 40, mp: 15, desc: "Restores 15 MP to one ally." },
};

// kind: phys uses atk, mag uses mag, heal restores HP. target: enemy | enemies | ally.
export const SKILLS = {
  blink_strike: { name: "Blink Strike", mp: 4, kind: "phys", power: 2, target: "enemy", anim: "thrust", desc: "Teleport behind a foe and strike twice as hard." },
  rift_burst: { name: "Rift Burst", mp: 8, kind: "mag", power: 1.1, target: "enemies", anim: "spellcast", desc: "Tear space open around every foe." },
  mend: { name: "Mend", mp: 5, kind: "heal", power: 35, target: "ally", anim: "spellcast", desc: "Heal one ally." },
  static_lance: { name: "Static Lance", mp: 5, kind: "mag", power: 1.8, target: "enemy", anim: "spellcast", desc: "A bolt of folded lightning." },
};

export const HEROES = {
  lead_m: { name: "Kai", base: { hp: 62, mp: 14, atk: 12, mag: 7, def: 7, spd: 11 }, grow: { hp: 9, mp: 2, atk: 3, mag: 1, def: 2, spd: 1 }, skills: ["blink_strike", "rift_burst"], attack: "slash" },
  lead_f: { name: "Mira", base: { hp: 50, mp: 22, atk: 9, mag: 12, def: 6, spd: 13 }, grow: { hp: 7, mp: 3, atk: 2, mag: 3, def: 1, spd: 1 }, skills: ["mend", "static_lance"], attack: "thrust" },
};

export const ENEMIES = {
  bat: { name: "Rift Bat", hp: 24, atk: 10, mag: 0, def: 3, spd: 15, xp: 6, gold: 4 },
  slime: { name: "Sump Slime", hp: 34, atk: 9, mag: 0, def: 5, spd: 7, xp: 7, gold: 5 },
  snake: { name: "Pipe Viper", hp: 28, atk: 12, mag: 0, def: 4, spd: 12, xp: 8, gold: 6 },
  eyeball: { name: "Watcher", hp: 30, atk: 6, mag: 11, def: 4, spd: 10, xp: 9, gold: 8, magic: true },
  spider_bot: { name: "Spider Drone", hp: 38, atk: 13, mag: 0, def: 8, spd: 9, xp: 11, gold: 10 },
  drone_tank: { name: "Directorate Tank", hp: 60, atk: 15, mag: 0, def: 10, spd: 6, xp: 18, gold: 20 },
  minotaur_mage: { name: "The Warden", hp: 260, atk: 17, mag: 15, def: 9, spd: 10, xp: 80, gold: 120, magic: true, boss: true },
};

export const statsAt = (id, lvl) => Object.fromEntries(Object.entries(HEROES[id].base).map(([k, v]) => [k, v + HEROES[id].grow[k] * (lvl - 1)]));

export function newHero(id, lvl = 1) {
  const s = statsAt(id, lvl);
  return { id, name: HEROES[id].name, lvl, xp: 0, ...s, maxhp: s.hp, maxmp: s.mp };
}

export const xpToNext = lvl => 12 * lvl * lvl;

/** Adds xp; returns how many levels were gained. Level-ups raise max HP/MP by the growth and keep current damage. */
export function gainXp(h, xp) {
  let ups = 0;
  h.xp += xp;
  while (h.xp >= xpToNext(h.lvl)) {
    h.xp -= xpToNext(h.lvl);
    h.lvl++; ups++;
    const g = HEROES[h.id].grow;
    for (const k of ["atk", "mag", "def", "spd"]) h[k] += g[k];
    h.maxhp += g.hp; h.maxmp += g.mp;
    if (h.hp > 0) { h.hp += g.hp; h.mp += g.mp; }
  }
  return ups;
}

/** Damage of one hit: attack stat against defence, scaled by power, +-10% spread, at least 1. Defending halves it. */
export function damage(att, def, power = 1, rand = Math.random, defending = false) {
  const base = Math.max(1, att * 2 - def) * power * (0.9 + 0.2 * rand());
  return Math.max(1, Math.round(defending ? base / 2 : base));
}

/** How far a time gauge (0..100) fills in dt milliseconds: speed 10 fills it in about three seconds. */
export const atbFill = (spd, dt) => (dt / 1000) * (spd + 20) * 1.1;

export function useItem(item, target) {
  const it = ITEMS[item];
  if (!it || target.hp <= 0) return false; // no raising the fallen in the slice
  if (it.hp) target.hp = Math.min(target.maxhp, target.hp + it.hp);
  if (it.mp) target.mp = Math.min(target.maxmp, target.mp + it.mp);
  return true;
}

export function newGame(lead) {
  const other = lead === "lead_m" ? "lead_f" : "lead_m";
  return { v: 1, party: [newHero(lead), newHero(other)], items: { potion: 3, ether: 1 }, gold: 60, map: "town", pos: null, flags: {},
    quest: null, offer: null, story: "", questsDone: 0, gifted: {}, cities: {} };
}

// ---- side quests (from Anansi or the written fallbacks) ------------------------------------------------------------

export const QUEST_REWARDS = { small: { gold: 30, items: {} }, medium: { gold: 60, items: { potion: 1 } }, large: { gold: 100, items: { ether: 1 } } };

/** The active quest {q, step}: moves on when (kind, id) is its current step. Returns "step", "done" or null. */
export function questStep(active, kind, id) {
  const s = active?.q.steps[active.step];
  if (!s || s.objective !== kind || s.target_id !== id) return null;
  active.step++;
  return active.step >= active.q.steps.length ? "done" : "step";
}

/** Pays a finished quest's reward into the save; returns the reward. Unknown tiers pay as small. */
export function payQuest(state, q) {
  const r = QUEST_REWARDS[q.reward_tier] || QUEST_REWARDS.small;
  state.gold += r.gold;
  for (const [id, n] of Object.entries(r.items)) state.items[id] = (state.items[id] || 0) + n;
  state.story = [state.story, q.story_summary].filter(Boolean).join(" ").slice(-800); // the newest part; the gateway cuts story_so_far at 1500 chars
  state.questsDone = (state.questsDone || 0) + 1;
  resetGifts(state); // a finished job is a reason for people to help again
  return r;
}

/** One gift (a heal or supplies) per NPC, until the party rests or finishes a quest. It is kept in the save, so it
 *  survives changing maps and reloading; keys are "<area>:<npc>". */
export const canGift = (s, key) => !s.gifted?.[key];
export const markGift = (s, key) => { (s.gifted ||= {})[key] = true; };
export const resetGifts = s => { s.gifted = {}; };

/** Tidies generated quest text: raw ids become names, and stray CJK characters (a small-model glitch) go. */
export function tidyQuest(q, names) {
  const fix = s => String(s).replace(/\b[a-z]+(?:_[a-z]+)+\b/g, w => names[w] || w)
    .replace(/[\p{Script=Han}\p{Script=Hangul}\p{Script=Hiragana}\p{Script=Katakana}]+/gu, "").replace(/\s+/g, " ").trim();
  return { ...q, title: fix(q.title), summary: fix(q.summary), story_summary: fix(q.story_summary),
    steps: q.steps.map(s => ({ ...s, description: fix(s.description) })) };
}

/** A quest is usable only if every step targets something this game has; generated quests are checked again here. */
export const questFits = (q, world) => !!q && Array.isArray(q.steps) && q.steps.length > 0 && q.steps.every(s =>
  ({ talk_to: world.npcs, explore: world.locations, fetch: world.items })[s.objective]?.some(e => e.id === s.target_id));
