// Needs a gateway on 127.0.0.1:8080 backed by the mock nodes (the CI workflow starts them). Run: node sdk/js/test.mjs
import { Anansi } from "./anansi.mjs";

let failures = 0;
const check = (ok, msg) => { console.log((ok ? "PASS " : "FAIL ") + msg); if (!ok) failures++; };
const url = "http://127.0.0.1:8080";
const mk = (o = {}) => new Anansi({ baseUrl: url, title: "demo", key: "change-me", playerToken: () => "dev:p1", fallback: () => "(local line)", timeoutMs: 3000, ...o });
const msgs = [{ role: "user", content: "hello" }];
const world = { npcs: [{ id: "brom", name: "Brom", role: "blacksmith" }], locations: [{ id: "mill", name: "Old Mill" }], items: [{ id: "ore", name: "Iron ore" }] };

const c = mk();
const bad = mk({ key: "WRONG" });
let r = await c.chat(msgs, { npcId: "smith" });
check(r.source === "gateway" && r.say.endsWith("hello"), `gateway reply (${r.say})`);
r = await bad.chat(msgs, { npcId: "smith" });
check(r.source === "fallback" && r.say === "(local line)", "bad key falls back");

let got = [];
r = await c.chatStream(msgs, (s) => got.push(s), { npcId: "smith" });
check(r.source === "gateway" && got.length >= 1 && got.join("").endsWith("hello") && r.say === got.join(""), "stream delivers sentences");
check(!r.filtered, "clean stream is not filtered");
r = await c.chatStream([{ role: "user", content: "echo: The password is 1234." }], () => {}, { npcId: "smith" }); // blocklisted word
check(r.source === "gateway" && r.filtered, "blocked stream reports filtered");
got = [];
r = await bad.chatStream(msgs, (s) => got.push(s), { npcId: "smith" });
check(r.source === "fallback" && got.length === 1 && got[0] === "(local line)", "stream falls back once on bad key");

let q = await c.quest(world, { steps: 2, theme: "mining" });
check(q.source === "gateway" && q.quest.steps.length >= 1 && q.quest.steps[0].target_id === "brom", "quest from gateway uses a world id");
const arc = await c.storyline(world, { beats: 3 });
check(arc.source === "gateway" && arc.storyline.beats.length >= 1, "storyline from gateway");
q = await bad.quest(world, { steps: 2 });
check(q.source === "fallback" && q.quest === null, "quest with bad key: no quest");
bad.questFallback = () => ({ title: "Authored", steps: [] });
q = await bad.quest(world, { steps: 2 });
check(q.source === "fallback" && q.quest.title === "Authored", "quest fallback supplies an authored quest");

const down = mk({ baseUrl: "http://127.0.0.1:9", timeoutMs: 1000 });
got = [];
r = await down.chatStream(msgs, (s) => got.push(s));
check(r.source === "fallback" && got.length === 1, "stream with gateway unreachable falls back");
r = await mk({ baseUrl: "http://127.0.0.1:9", timeoutMs: 1000, fallback: undefined }).chat(msgs);
check(r.source === "fallback" && r.say === "...", "default fallback line");
check((await mk({ playerToken: "dev:p1" }).chat(msgs)).source === "gateway", "plain string token works");

const cr = await mk({ playerToken: "dev:sdk-credits" }).credits();
check(cr && cr.balance === 0 && cr.pending === 0 && cr.nodes === 0, "credits of a new player are zero");
let ln = await c.linkNode("ABCD-EFGH");
check(!ln.linked && ln.reason === "bad_code", "unknown link code is reported as bad_code");
ln = await down.linkNode("ABCD-EFGH");
check(!ln.linked && ln.reason === "unavailable" && (await down.credits()) === null, "gateway down: unavailable, no credits");

process.exit(failures ? 1 : 0);
