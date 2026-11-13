// The field menu (Esc / X): party summary, Items, Status, Story, Quests, Teleport, Save.
/* global Phaser */
import { G, save } from "./state.js";
import { mapFor, areaOf, areaLabel, cityId } from "./world.js";
import { fetchAtlas, atlasCached, suggestions } from "./anansi.js";
import { cleanDest } from "./atlas.js";
import { ACTS, objective } from "./story.js";
import { ITEMS, SKILLS, HEROES, xpToNext, useItem } from "./rules.js";
import { W, H, drawWindow, text, choose, say, prompt, waitFor } from "./ui.js";

export class Menu extends Phaser.Scene {
  constructor() { super("menu"); }

  create() {
    this.add.rectangle(0, 0, W, H, 0x000000, 0.35).setOrigin(0);
    drawWindow(this, 8, 8, 470, H - 16);
    this.summary = text(this, 26, 24, "", { lineSpacing: 6 });
    drawWindow(this, 486, H - 64, 146, 56);
    this.goldTxt = text(this, 500, H - 48, "");
    this.loop();
  }

  draw() {
    this.summary.setText(G.s.party.map(h =>
      `${h.name}   Lv ${h.lvl}\n  HP ${h.hp}/${h.maxhp}   MP ${h.mp}/${h.maxmp}\n  next level in ${xpToNext(h.lvl) - h.xp} XP\n`).join("\n"));
    this.goldTxt.setText(`${G.s.gold} G`);
  }

  async loop() {
    for (;;) {
      this.draw();
      const k = await choose(this, 486, 8, 146, ["Items", "Status", "Story", "Quests", "Teleport", "Save", "Close"]);
      if (k === 0) await this.items();
      else if (k === 1) await this.status();
      else if (k === 2) await this.story();
      else if (k === 3) await this.quests();
      else if (k === 4) { if (await this.teleport()) return; }
      else if (k === 5) await say(this, "", save() ? "Game saved." : "Could not save (browser storage is blocked).");
      else return this.close();
    }
  }

  async items() {
    for (;;) {
      const ids = Object.keys(G.s.items).filter(id => G.s.items[id] > 0);
      if (!ids.length) return say(this, "", "No items.");
      const help = text(this, 26, H - 40, "");
      const k = await choose(this, 250, 40, 220, ids.map(id => `${ITEMS[id].name.padEnd(9)} x${G.s.items[id]}`), { onMove: i => help.setText(ITEMS[ids[i]].desc) });
      help.destroy();
      if (k < 0) return;
      const who = await choose(this, 250, 160, 220, G.s.party.map(h => ({ label: `${h.name} ${h.hp}/${h.maxhp}`, disabled: h.hp <= 0 })));
      if (who >= 0 && useItem(ids[k], G.s.party[who])) G.s.items[ids[k]]--;
      this.draw();
    }
  }

  async status() {
    for (const h of G.s.party) {
      await say(this, h.name, `Lv ${h.lvl}  ATK ${h.atk}  MAG ${h.mag}  DEF ${h.def}  SPD ${h.spd}\nSkills: ${HEROES[h.id].skills.map(s => SKILLS[s].name).join(", ")}`);
    }
  }

  async story() {
    const p = G.s.plot;
    const lines = [ACTS[p.act] || ACTS[1], "", objective(p)];
    if (p.act === 2) lines.push("", `Relays destroyed: ${p.relays.length ? p.relays.join(", ") : "none yet"}`);
    const win = drawWindow(this, 8, 8, 470, H - 16);
    const body = text(this, 26, 24, lines.join("\n"), { wordWrap: { width: 430 }, lineSpacing: 6 });
    await choose(this, 486, H - 140, 146, ["Back"]);
    win.destroy(); body.destroy();
  }

  async quests() {
    const a = G.s.quest;
    if (!a) return say(this, "", `No quest right now. ${G.s.questsDone ? `Finished: ${G.s.questsDone}. ` : ""}Ines in Old Town, and the first local you meet in a new city, often have work.`);
    const spots = areaOf(a.area).itemSpots;
    const where = s => (s.objective === "fetch" && spots[s.target_id] ? ` (${mapFor(spots[s.target_id][0]).name})` : "");
    const steps = a.q.steps.map((s, i) => `${i < a.step ? "✔" : i === a.step ? "▶" : "·"} ${s.description}${where(s)}`).join("\n");
    const win = drawWindow(this, 8, 8, 470, H - 16);
    const body = text(this, 26, 24, `${a.q.title} (${areaLabel(a.area)})\n\n${a.q.summary}\n\n${steps}`, { wordWrap: { width: 430 }, lineSpacing: 5 });
    await choose(this, 486, H - 140, 146, ["Back"]);
    win.destroy(); body.destroy();
  }

  /** Teleport: to Old Town, a city you have been to, or a new place named by the player. Returns true if the party left. */
  async teleport() {
    const here = G.s.map;
    const entries = [{ label: "Type a place…" }, ...suggestions().map(d => ({ label: d + (atlasCached(d) ? " ✦" : ""), dest: d })), // ✦: ready, no waiting
      ...(G.s.plot.spire && here !== "spire" ? [{ label: "Directorate Spire", map: "spire" }] : []),
      ...(here === "town" ? [] : [{ label: "Old Town", map: "town" }]),
      ...Object.keys(G.s.cities).filter(d => cityId(d) !== here).slice(-6).map(d => ({ label: d.slice(0, 20), map: cityId(d) }))];
    const k = await choose(this, 250, 40, 220, entries.map(e => e.label));
    if (k < 0) return false;
    let map = entries[k].map;
    if (!map) {
      const dest = entries[k].dest || cleanDest((await prompt(this, "Where to? Any real place on Earth:")) || "");
      if (!dest) return false;
      const known = Object.keys(G.s.cities).find(d => d.toLowerCase() === dest.toLowerCase());
      if (known && !G.s.cities[known].generic) map = cityId(known);
      else {
        const name = known || dest, key = cityId(name);
        const r = await waitFor(this, fetchAtlas(name), `Folding space to ${name}`);
        G.s.cities[name] = { atlas: r.atlas, climate: r.climate, generic: r.source === "fallback" }; // generic: the gateway could not say anything about it
        if (G.s.quest?.area === key) G.s.quest = null; // a rebuilt city has new people: an old job there no longer fits
        if (G.s.offer?.area === key) G.s.offer = null;
        map = key;
      }
    }
    this.close();
    this.scene.get("field").teleportTo(map);
    return true;
  }

  close() {
    this.scene.stop();
    this.scene.resume("field");
  }
}
