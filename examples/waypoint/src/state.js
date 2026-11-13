// The one game state (party, items, gold, where the party is, story flags) and saving it in the browser.
import { newGame } from "./rules.js";

const KEY = "waypoint.save";
export const G = { s: null };

export const start = lead => (G.s = newGame(lead));
export function save() {
  try { localStorage.setItem(KEY, JSON.stringify(G.s)); return true; } catch { return false; }
}
export function load() {
  try { const s = JSON.parse(localStorage.getItem(KEY)); if (s?.v === 1) return (G.s = s); } catch { /* corrupt or blocked */ }
  return null;
}
export const hasSave = () => { try { return !!localStorage.getItem(KEY); } catch { return false; } };
