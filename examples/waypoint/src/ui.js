// Menu windows, dialogue and list choosers. Each returns a Promise so scenes can `await` the player.
/* global Phaser */
export const W = 640, H = 360;
export const FONT = { fontFamily: "monospace", fontSize: "14px", color: "#ffffff" };
const OK = ["ENTER", "SPACE", "Z"], BACK = ["ESC", "X", "BACKSPACE"];
const UI_DEPTH = 10000;

// SNES-style window: blue gradient with a light double border. Fixed to the screen, above the world.
export function drawWindow(scene, x, y, w, h) {
  const g = scene.add.graphics().setScrollFactor(0).setDepth(UI_DEPTH);
  g.fillGradientStyle(0x2a3a9c, 0x2a3a9c, 0x0c1240, 0x0c1240, 0.96);
  g.fillRoundedRect(x, y, w, h, 6);
  g.lineStyle(3, 0xe8ecff, 1).strokeRoundedRect(x + 1, y + 1, w - 2, h - 2, 6);
  g.lineStyle(1, 0x7a86c8, 1).strokeRoundedRect(x + 4, y + 4, w - 8, h - 8, 4);
  return g;
}
export const text = (scene, x, y, s, style = {}) => scene.add.text(x, y, s, { ...FONT, ...style }).setScrollFactor(0).setDepth(UI_DEPTH + 1);

/** Calls fn(keyName) for each key press until the returned stop() is called. */
function listen(scene, fn) {
  const h = e => fn(e.key === " " ? "SPACE" : e.key.length === 1 ? e.key.toUpperCase() : e.key.replace(/^Arrow/, "").toUpperCase().replace("ESCAPE", "ESC"));
  scene.input.keyboard.on("keydown", h);
  return () => scene.input.keyboard.off("keydown", h);
}

/** One line of dialogue in a box at the bottom, typed out; any confirm key finishes the line, then closes it. */
export function say(scene, name, line) {
  return new Promise(done => {
    const parts = [drawWindow(scene, 8, H - 96, W - 16, 88)];
    if (name) parts.push(text(scene, 22, H - 88, name, { color: "#ffd76a" }));
    const body = text(scene, 22, H - (name ? 68 : 82), "", { wordWrap: { width: W - 48 }, lineSpacing: 4 });
    const more = text(scene, W - 34, H - 28, "▼", { color: "#ffd76a" }).setVisible(false);
    parts.push(body, more);
    let shown = 0;
    const timer = scene.time.addEvent({ delay: 22, loop: true, callback: () => {
      shown = Math.min(line.length, shown + 1); body.setText(line.slice(0, shown));
      if (shown === line.length) { timer.remove(); more.setVisible(true); }
    } });
    const stop = listen(scene, k => {
      if (!OK.includes(k)) return;
      if (shown < line.length) { shown = line.length; body.setText(line); timer.remove(); more.setVisible(true); return; }
      stop(); parts.forEach(p => p.destroy()); done();
    });
  });
}

/** Several lines; each entry is "text" or [name, "text"]. */
export async function talk(scene, lines, name) {
  for (const l of lines) Array.isArray(l) ? await say(scene, l[0], l[1]) : await say(scene, name, l);
}

/**
 * A vertical list in a window. items: strings or {label, disabled}. Resolves with the chosen index, or -1 when
 * cancelled (if cancel is allowed). onMove(i) runs as the cursor moves, e.g. to show a description.
 */
export function choose(scene, x, y, w, items, { cancel = true, onMove, keep = false, rowH = 22 } = {}) {
  return new Promise(done => {
    items = items.map(i => (typeof i === "string" ? { label: i } : i));
    const win = drawWindow(scene, x, y, w, items.length * rowH + 20);
    const labels = items.map((it, i) => text(scene, x + 30, y + 11 + i * rowH, it.label, { color: it.disabled ? "#7f86a8" : "#ffffff" }));
    const cur = text(scene, x + 12, 0, "▶", { color: "#ffd76a" });
    let i = Math.max(0, items.findIndex(it => !it.disabled));
    const move = d => { i = (i + d + items.length) % items.length; cur.setY(y + 11 + i * rowH); onMove?.(i); };
    move(0);
    const close = r => { stop(); if (!keep) [win, cur, ...labels].forEach(o => o.destroy()); done(r); };
    const stop = listen(scene, k => {
      if (k === "UP") move(-1);
      else if (k === "DOWN") move(1);
      else if (OK.includes(k) && !items[i].disabled) close(i);
      else if (BACK.includes(k) && cancel) close(-1);
    });
    choose.last = { win, cur, labels }; // for callers that keep the window open (keep: true) and destroy it later
  });
}

/** Moves a ▶ between on-screen targets ({x, y}); resolves with the index or -1 on cancel. */
export function pickTarget(scene, targets, start = 0) {
  return new Promise(done => {
    const cur = text(scene, 0, 0, "▶", { color: "#ffd76a", fontSize: "20px" }).setOrigin(1, 0.5);
    let i = start;
    const place = () => cur.setPosition(targets[i].x, targets[i].y);
    place();
    const stop = listen(scene, k => {
      if (["UP", "LEFT"].includes(k)) { i = (i - 1 + targets.length) % targets.length; place(); }
      else if (["DOWN", "RIGHT"].includes(k)) { i = (i + 1) % targets.length; place(); }
      else if (OK.includes(k) || BACK.includes(k)) { stop(); cur.destroy(); done(OK.includes(k) ? i : -1); }
    });
  });
}

export const tween = (scene, cfg) => new Promise(r => scene.tweens.add({ ...cfg, onComplete: r }));
export const wait = (scene, ms) => new Promise(r => scene.time.delayedCall(ms, r));
