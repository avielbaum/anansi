// Everything that talks to the Anansi gateway: free-text NPC replies and generated side quests.
// The SDK answers from the fallbacks when the gateway is down or slow, so the game never waits on it for long.
import { Anansi } from "../../../sdk/js/anansi.mjs";
import { QUEST_WORLD, FALLBACK_QUESTS, PERSONAS, SHORT_NAMES } from "./data.js";
import { questFits, tidyQuest } from "./rules.js";
import { G } from "./state.js";

// shortcut: the title key sits in the page, fine for a local dev gateway; a shipped game proxies through its own server.
const params = new URLSearchParams(location.search);
const playerId = (() => { try { return (localStorage.waypointPid ||= Math.random().toString(36).slice(2)); } catch { return "guest"; } })();

const client = new Anansi({
  baseUrl: params.get("gateway") || "http://localhost:8080",
  title: "waypoint", key: params.get("key") || "change-me", playerToken: "dev:" + playerId,
  timeoutMs: 45000, generationTimeoutMs: 120000, // CPU-only models are slow
  questFallback: () => FALLBACK_QUESTS[(G.s.questsDone || 0) % FALLBACK_QUESTS.length],
});

const history = {}; // npc id -> recent messages, for this session only

function persona(id) {
  const p = PERSONAS[id], [lead, mate] = G.s.party, a = G.s.quest;
  const task = a ? ` The hero is working on "${a.q.title}"; the current step: ${a.q.steps[a.step]?.description}` : "";
  return `${p.bio} The hero, ${lead.name}, and their companion, ${mate.name}, can teleport. They just arrived in Old Town on the run from the Directorate.` +
    (G.s.flags.warden ? " They have defeated the Directorate's Warden in the Undercroft." : " The Directorate's Warden guards the Undercroft.") +
    `${task} The hero has ${lead.hp} of ${lead.maxhp} health. ${p.acts} Never mention being an AI.`;
}

/** One free-text exchange with an NPC: {say, action, source}. */
export async function ask(id, line) {
  const h = (history[id] ||= []);
  h.push({ role: "user", content: line });
  client.fallback = () => PERSONAS[id].fallback[Math.floor(Math.random() * PERSONAS[id].fallback.length)];
  const r = await client.chat([{ role: "system", content: persona(id) }, ...h.slice(-8)], { npcId: id, structured: true });
  h.push({ role: "assistant", content: r.say });
  return r;
}

let pending = null;
/** Starts generating the next side quest in the background (quests take 30-60 s on CPU). */
export function prefetchQuest() {
  pending ||= client.quest(QUEST_WORLD, {
    steps: 3, theme: "a side job in Old Town while the Directorate watches", storySoFar: G.s.story || "",
    player: `${G.s.party[0].name}, a level ${G.s.party[0].lvl} teleporter`,
  }).then(r => (questFits(r.quest, QUEST_WORLD) ? { ...r, quest: tidyQuest(r.quest, SHORT_NAMES) } : { source: "fallback", quest: client.questFallback() }));
  return pending;
}
/** The prefetched quest (waits for it if needed); the next call starts a new one. */
export function takeQuest() { const p = prefetchQuest(); pending = null; return p; }
