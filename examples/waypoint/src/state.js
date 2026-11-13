// The one game state (party, items, gold, where the party is, story flags) and saving it in the browser.
import { newGame } from "./rules.js";

const KEY = "waypoint.save";
export const G = { s: null };

export const start = lead => (G.s = newGame(lead));
export function save() {
  try { localStorage.setItem(KEY, JSON.stringify(G.s)); return true; } catch { return false; }
}
export function load() {
  try { const s = JSON.parse(localStorage.getItem(KEY)); if (s?.v === 1) return (G.s = upgrade(s)); } catch { /* corrupt or blocked */ }
  return null;
}

/** Fills in what older saves lack, so a save from an earlier build still loads. */
export function upgrade(s) {
  s.gifted ||= {}; s.cities ||= {}; s.story ||= ""; s.questsDone ||= 0;
  if (s.quest && !s.quest.area) s.quest.area = "home";
  if (s.offer && !s.offer.q) s.offer = { q: s.offer, area: "home" };
  if (s.map.startsWith("city:") && !s.cities[s.map.slice(5)]) { s.map = "town"; s.pos = null; } // its city data is missing
  return s;
}
export const hasSave = () => { try { return !!localStorage.getItem(KEY); } catch { return false; } };
