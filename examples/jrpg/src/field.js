// The walking scene: one class for every map in data.js.
/* global Phaser */
import { MAPS, STAMPS, TALK } from "./data.js";
import { G } from "./state.js";
import { ITEMS } from "./rules.js";
import { W, H, drawWindow, text, talk, choose, say } from "./ui.js";

const T = 32, DIRS = ["up", "left", "down", "right"], SPEED = 110;
const VEC = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };
const feet = (tx, ty) => ({ x: tx * T + 16, y: ty * T + 28 });
const hit = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;

export class Field extends Phaser.Scene {
  constructor() { super("field"); }

  init(d) { this.mapId = d.map || G.s.map; this.at = d.at || G.s.pos || feet(...MAPS[this.mapId].spawn); }

  create() {
    const M = (this.M = MAPS[this.mapId]);
    G.s.map = this.mapId;
    this.cast = this.cache.json.get("cast");
    this.solids = [];
    this.things = []; // things you can face and press confirm at: {box, act}
    this.add.tileSprite(0, 0, M.w * T, M.h * T, `tile-${M.ground}`).setOrigin(0).setDepth(-10);
    for (const [tex, x, y, w, h, solid] of M.paint) {
      this.add.tileSprite(x * T, y * T, w * T, h * T, `tile-${tex}`).setOrigin(0).setDepth(-9);
      if (solid) this.solids.push({ x: x * T, y: y * T, w: w * T, h: h * T });
    }
    for (const [key, tx, ty, opt = {}] of M.objects) this.addStamp(key, tx, ty, opt);
    for (const [s, tx, ty] of M.labels || []) this.add.text(tx * T, ty * T, s, { fontFamily: "monospace", fontSize: "11px", color: "#fff", stroke: "#000", strokeThickness: 3 }).setOrigin(0.5).setDepth(5000);
    for (const n of M.npcs || []) this.addNpc(n);
    if (M.boss && !G.s.flags[M.boss.flag]) {
      const p = feet(M.boss.x, M.boss.y);
      this.bossImg = this.add.image(p.x, p.y, `enemy-${M.boss.enemy}`).setOrigin(0.5, 1).setDepth(p.y);
      this.solids.push((this.bossBox = { x: p.x - 24, y: p.y - 16, w: 48, h: 16 }));
    }

    const [lead, mate] = G.s.party.map(h => h.id);
    this.hero = this.addActor(lead, this.at.x, this.at.y, "down");
    this.mate = this.addActor(mate, this.at.x, this.at.y - 24, "down"); // a step behind (north of) the lead
    this.hero.s.setDepth(this.at.y + 0.5); this.mate.s.setDepth(this.at.y - 24);
    this.trail = [];
    this.cameras.main.setBounds(0, 0, M.w * T, M.h * T).startFollow(this.hero.s, true).setRoundPixels(true);
    this.keys = this.input.keyboard.addKeys("UP,DOWN,LEFT,RIGHT,W,A,S,D");
    this.input.keyboard.on("keydown", e => this.onKey(e.key));
    this.inZone = this.zonesAt(this.hero.s).length > 0; // arriving on an exit does not bounce you back
    this.nextFight = Phaser.Math.Between(500, 900);
    this.events.on("resume", () => { this.input.keyboard.resetKeys(); });
    this.cameras.main.fadeIn(250);
    const banner = this.add.text(W / 2, 30, M.name, { fontFamily: "monospace", fontSize: "18px", color: "#fff", stroke: "#000", strokeThickness: 4 }).setOrigin(0.5).setScrollFactor(0).setDepth(9000);
    this.tweens.add({ targets: banner, alpha: 0, delay: 1500, duration: 600, onComplete: () => banner.destroy() });
    if (M.intro && !G.s.flags[M.intro]) { G.s.flags[M.intro] = true; this.run(() => this.lines(TALK[M.intro])); }
  }

  addStamp(key, tx, ty, opt) {
    const st = STAMPS[key], x = tx * T, y = ty * T;
    if (opt.chest && G.s.flags[opt.chest]) return this.add.image(x, y, "tile-chest").setOrigin(0).setDepth(y + st.h).setTint(0x777777);
    const img = this.add.image(x, y, `tile-${key}`).setOrigin(0).setDepth(st.flat ? -5 : y + st.h);
    if (st.foot) {
      const box = { x: x + st.foot[0], y: y + st.foot[1], w: st.foot[2], h: st.foot[3] };
      this.solids.push(box);
      if (opt.chest) { const t = { box, act: () => this.openChest(img, opt, t) }; this.things.push(t); }
    }
    return img;
  }

  addActor(id, x, y, dir) {
    const s = this.add.sprite(x, y, `${id}-walk`).setOrigin(0.5, 58 / 64);
    const a = { id, s, dir };
    this.face(a, dir, false);
    return a;
  }

  addNpc(n) {
    const p = feet(n.x, n.y), a = this.addActor(n.id, p.x, p.y, n.dir);
    a.s.setDepth(p.y);
    const box = { x: p.x - 12, y: p.y - 12, w: 24, h: 14 };
    this.solids.push(box);
    this.things.push({ box, act: () => this.talkTo(n, a) });
  }

  face(a, dir, moving) {
    a.dir = dir;
    if (moving) a.s.play(`${a.id}-walk-${dir}`, true);
    else a.s.stop().setFrame(DIRS.indexOf(dir) * this.cast[a.id].anims.walk.frames);
  }

  /** Runs a cutscene/menu with movement locked. */
  async run(fn) {
    this.busy = true;
    this.face(this.hero, this.hero.dir, false); this.face(this.mate, this.mate.dir, false);
    try { await fn(); } finally { this.busy = false; this.input.keyboard.resetKeys(); }
  }

  /** Dialogue lines with LEAD/MATE replaced by the party's names. */
  lines(ls, speaker) {
    const name = id => G.s.party.find(h => h.id === id)?.name || this.cast[id]?.name || id;
    const [lead, mate] = G.s.party.map(h => h.id);
    return talk(this, ls.map(l => (Array.isArray(l) ? [l[0] === "LEAD" ? name(lead) : l[0] === "MATE" ? name(mate) : l[0], l[1]] : l)), speaker);
  }

  talkTo(n, a) {
    const opposite = { up: "down", down: "up", left: "right", right: "left" }[this.hero.dir];
    this.face(a, opposite, false);
    const who = this.cast[n.id].name === "Shopkeeper" ? "Tobias" : this.cast[n.id].name;
    const t = TALK[n.talk];
    this.run(async () => {
      if (n.talk === "shop") return this.shop(who);
      await this.lines(Array.isArray(t) ? t : G.s.flags.warden ? t.after : t.before, who);
      this.face(a, n.dir, false);
    });
  }

  async shop(who) {
    await say(this, who, TALK.shop[0]);
    for (;;) {
      const goldWin = drawWindow(this, W - 150, 8, 142, 40), goldTxt = text(this, W - 136, 20, `${G.s.gold} G`);
      const pick = await choose(this, W - 210, 56, 200, ["Buy", "Rest (10 G)", "Leave"]);
      goldWin.destroy(); goldTxt.destroy();
      if (pick === 0) {
        const ids = Object.keys(ITEMS);
        const desc = text(this, 20, H - 40, "");
        const k = await choose(this, W - 260, 56, 250, ids.map(id => ({ label: `${ITEMS[id].name.padEnd(8)} ${String(ITEMS[id].price).padStart(3)} G  x${G.s.items[id] || 0}`, disabled: G.s.gold < ITEMS[id].price })),
          { onMove: i => desc.setText(ITEMS[ids[i]].desc) });
        desc.destroy();
        if (k >= 0) { G.s.gold -= ITEMS[ids[k]].price; G.s.items[ids[k]] = (G.s.items[ids[k]] || 0) + 1; await say(this, who, `One ${ITEMS[ids[k]].name}. Thank you kindly!`); }
      } else if (pick === 1) {
        if (G.s.gold < 10) { await say(this, who, "Ten gold for the cot in the back, I'm afraid."); continue; }
        G.s.gold -= 10;
        await new Promise(r => { this.cameras.main.fadeOut(400); this.cameras.main.once("camerafadeoutcomplete", r); });
        G.s.party.forEach(h => { h.hp = h.maxhp; h.mp = h.maxmp; });
        this.cameras.main.fadeIn(400);
        await say(this, who, "Rested and ready. Mind the tunnels.");
      } else return say(this, who, "Come back any time!");
    }
  }

  openChest(img, opt, t) {
    this.run(async () => {
      G.s.flags[opt.chest] = true;
      G.s.items[opt.item] = (G.s.items[opt.item] || 0) + opt.n;
      img.setTint(0x777777);
      this.things = this.things.filter(x => x !== t);
      await say(this, "", `Found ${opt.n} × ${ITEMS[opt.item].name}!`);
    });
  }

  onKey(k) {
    if (this.busy || !this.scene.isActive()) return;
    if (["Enter", " ", "z", "Z"].includes(k)) {
      const [dx, dy] = VEC[this.hero.dir], s = this.hero.s;
      const probe = { x: s.x + dx * 22 - 6, y: s.y + dy * 20 - 10, w: 12, h: 12 };
      this.things.find(t => hit(probe, t.box))?.act();
    } else if (["Escape", "x", "X"].includes(k)) {
      this.busy = true;
      this.face(this.hero, this.hero.dir, false); this.face(this.mate, this.mate.dir, false);
      G.s.pos = { x: this.hero.s.x, y: this.hero.s.y };
      this.scene.launch("menu"); this.scene.pause();
      this.events.once("resume", () => { this.busy = false; });
    }
  }

  blocked(x, y) {
    const b = { x: x - 9, y: y - 8, w: 18, h: 10 };
    if (b.x < 0 || b.y < 0 || b.x + b.w > this.M.w * T || b.y + b.h > this.M.h * T) return true;
    return this.solids.some(s => hit(b, s));
  }

  zonesAt(s) { return (this.M.zones || []).filter(z => hit({ x: s.x - 2, y: s.y - 2, w: 4, h: 4 }, { x: z.x * T, y: z.y * T, w: z.w * T, h: z.h * T })); }

  update(_t, dt) {
    if (this.busy) return;
    const k = this.keys, h = this.hero, s = h.s;
    const dx = (k.RIGHT.isDown || k.D.isDown) - (k.LEFT.isDown || k.A.isDown), dy = (k.DOWN.isDown || k.S.isDown) - (k.UP.isDown || k.W.isDown);
    const moving = dx || dy;
    if (moving) {
      const v = (SPEED * Math.min(dt, 50)) / 1000, ox = s.x, oy = s.y;
      if (dx && !this.blocked(s.x + dx * v, s.y)) s.x += dx * v;
      if (dy && !this.blocked(s.x, s.y + dy * v)) s.y += dy * v;
      const dir = dy ? (dy < 0 ? "up" : "down") : dx < 0 ? "left" : "right";
      this.face(h, dir, true);
      const moved = Math.hypot(s.x - ox, s.y - oy);
      if (moved) { this.trail.push({ x: s.x, y: s.y, dir }); this.afterStep(moved); }
    } else this.face(h, h.dir, false);
    let p = null; // the companion walks the lead's path ~30px behind
    while (this.trail.length && Phaser.Math.Distance.Between(this.trail[0].x, this.trail[0].y, s.x, s.y) > 30) p = this.trail.shift();
    if (p) { this.mate.s.setPosition(p.x, p.y); this.face(this.mate, p.dir, true); } else this.face(this.mate, this.mate.dir, false);
    s.setDepth(s.y + 0.5); this.mate.s.setDepth(this.mate.s.y);
  }

  afterStep(moved) {
    const zones = this.zonesAt(this.hero.s);
    if (zones.length && !this.inZone) {
      this.inZone = true;
      const z = zones[0];
      if (z.go) return this.goTo(z.go);
      if (z.boss && !G.s.flags[this.M.boss.flag]) return this.bossFight();
    }
    if (!zones.length) this.inZone = false;
    if (this.M.encounters && (this.nextFight -= moved) <= 0) {
      this.nextFight = Phaser.Math.Between(550, 1000);
      this.battle(Phaser.Utils.Array.GetRandom(this.M.encounters));
    }
  }

  goTo(go) {
    this.busy = true;
    G.s.pos = null;
    this.cameras.main.fadeOut(250);
    this.cameras.main.once("camerafadeoutcomplete", () => this.scene.restart({ map: go.map, at: feet(go.x, go.y) }));
  }

  bossFight() {
    this.run(async () => {
      await this.lines(TALK.warden, "The Warden");
      await this.battle([this.M.boss.enemy], true);
    });
  }

  /** Starts a battle over this scene; resolves when it ends and the field is back. */
  battle(enemies, boss = false) {
    this.busy = true;
    this.face(this.hero, this.hero.dir, false); this.face(this.mate, this.mate.dir, false);
    G.s.pos = { x: this.hero.s.x, y: this.hero.s.y };
    return new Promise(done => {
      this.cameras.main.flash(300, 255, 255, 255);
      this.time.delayedCall(300, () => {
        this.scene.launch("battle", { enemies, bg: this.M.battle, boss, onEnd: async result => {
          this.scene.resume();
          this.busy = false;
          if (result === "won" && boss) {
            G.s.flags[this.M.boss.flag] = true;
            this.bossImg?.destroy();
            this.solids = this.solids.filter(sb => sb !== this.bossBox);
            await this.run(() => this.lines(TALK.won));
          }
          done(result);
        } });
        this.scene.pause();
      });
    });
  }
}
