export interface Message { role: "system" | "user" | "assistant"; content: string }
export interface Reply { source: "gateway" | "fallback"; say: string; action: string; filtered: boolean }
export interface Entity { id: string; name: string; role?: string }
export interface World { npcs?: Entity[]; locations?: Entity[]; items?: Entity[] }
export interface QuestStep { objective: "talk_to" | "explore" | "fetch"; target_id: string; description: string }
export interface Quest { title: string; summary: string; steps: QuestStep[]; reward_tier: "small" | "medium" | "large"; story_summary: string }
export interface Beat { title: string; summary: string; npc_id?: string; location_id?: string }
export interface Storyline { logline: string; beats: Beat[] }

export interface Credits { balance: number; pending: number; nodes: number }
export type LinkResult = ({ linked: true } & Credits) | { linked: false; reason: "bad_code" | "unavailable" };

export interface Options {
  baseUrl: string;
  title: string;
  key: string;
  playerToken: string | (() => string | Promise<string>);
  fallback?: (messages: Message[]) => string | Promise<string>;
  questFallback?: (world: World) => Quest | null | Promise<Quest | null>;
  storylineFallback?: (world: World) => Storyline | null | Promise<Storyline | null>;
  timeoutMs?: number;
  streamTimeoutMs?: number;
  generationTimeoutMs?: number;
  fetch?: typeof fetch;
}

export class Anansi {
  constructor(options: Options);
  chat(messages: Message[], opts?: { npcId?: string; structured?: boolean }): Promise<Reply>;
  chatStream(messages: Message[], onSentence: (sentence: string) => void, opts?: { npcId?: string }): Promise<Reply>;
  quest(world: World, opts?: { steps?: number; theme?: string; difficulty?: string; storySoFar?: string; player?: string }):
    Promise<{ source: "gateway" | "fallback"; quest: Quest | null }>;
  storyline(world: World, opts?: { beats?: number; theme?: string }):
    Promise<{ source: "gateway" | "fallback"; storyline: Storyline | null }>;
  credits(): Promise<Credits | null>;
  linkNode(code: string): Promise<LinkResult>;
  questFallback?: (world: World) => Quest | null | Promise<Quest | null>;
  storylineFallback?: (world: World) => Storyline | null | Promise<Storyline | null>;
}
