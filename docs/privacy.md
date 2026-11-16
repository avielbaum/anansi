# Privacy: what Anansi collects, publishes and keeps

> **Draft for counsel review.** This describes what the software does today. It is not legal advice and not a finished policy.
> Whoever runs a gateway (the *operator*) is responsible for their own legal basis, notices and compliance, and has to fill in the
> placeholders in [brackets]. Where the code does not do something yet, this page says so under "Not handled yet".

## Who is who

| | |
|---|---|
| **Operator** | Runs a gateway: [OPERATOR NAME AND ADDRESS]. Contact for privacy requests: [CONTACT]. Decides what is kept and for how long. |
| **Studio** | The game publisher whose game calls the gateway. May be the operator. Decides whether volunteers may serve its title (`allow_volunteers`). |
| **Volunteer** | Someone who runs the node agent (`node/agent.py`, `join`) so their computer answers game dialogue. |
| **Player** | Someone playing a game that uses the gateway. |

## What the software stores

| Data | About | Why | Kept |
|---|---|---|---|
| Player id (from the operator's verifier), tokens used per day | Player | Daily token budget, so one account cannot use everything | `retention_days` (35), then deleted |
| The text of a player's message and the NPC's reply | Player | Not stored: processed in memory by the gateway and sent to whichever model answers (see below). The operator's own logging or proxy may differ | Not stored by the gateway |
| A random agent id, tokens and jobs served per day, probe results, bans | Volunteer | Verification and the work ledger | No automatic deletion (see "Not handled yet") |
| A link between an agent id and a player's account, earned and spent credits | Volunteer / player | Volunteer credits | While credits exist (no automatic deletion) |
| **Statistics report (opt-in)**: CPU model, GPU models and memory, operating system name, a slow average of idle GPU load, and when it last arrived | Volunteer | The anonymous network statistics below | Until the volunteer deletes it (`--telemetry-off`), or **2 days after the last report** |

The statistics report is the only thing a machine sends beyond doing jobs, and it is off unless the volunteer starts the agent with
`--telemetry`. It contains **no name, account, address, hostname, user name, serial number, driver version or thread count**
(`--telemetry-show` prints it exactly), and an agent has no option to add a name.

## What is published: anonymous statistics

The page `/leaderboard` and the JSON `/v1/leaderboard` show **statistics about groups of machines**, not machines or people:

- how many machines are reporting, the tokens they served (today, 7 days, all time), and a typical idle GPU load;
- the same broken down by **graphics card** (model and memory), **processor** model and **operating system**: machines, tokens served
  and typical idle load per group, most tokens first;
- the tokens served by the whole volunteer network, for comparison.

How it stays anonymous:

- **A group is shown only if at least `min_group` machines are in it** (default 5). Smaller groups are folded into "Other" if together
  they reach `min_group`, and are otherwise left out. **Nothing at all is published until `min_group` machines report**, not even a count.
  So no row describes a single computer or a single person, and a rare build cannot point at its owner.
- **No name, account, agent id, hash, rank of a person, per-machine row, jobs per machine or time of day** is published, and there is no
  display name anywhere to choose. The last report is never shown.
- **The idle figure is a slow average** (hours) of what machines report, and a group's figure is the mean of its machines, shown as a whole
  percent, so it cannot reveal when anyone is playing.
- A machine's tokens are counted once, under its graphics card with the most memory.
- Hardware text comes from outside and is cleaned (invisible and right-to-left characters removed, lengths capped) and escaped; a group
  needs `min_group` machines reporting the very same text, and the operator can hide hardware by pattern (`leaderboard.hidden_hardware`).
- The page asks search engines not to index it and cannot be framed by other sites.

## How anonymous is it, exactly

Be precise about this rather than rely on the word.

- **What anyone can see is anonymous** in the sense above: groups of at least `min_group` machines, nothing about an individual.
- **Small numbers weaken it.** An operator who sets `min_group` to 1 (allowed, for testing) publishes single machines, and the page says so.
  With 5, someone who watches the page over time can see that a group grew from 5 to 6 machines, which says a machine joined, not whose.
- **The operator's database is pseudonymous, not anonymous, for up to 2 days.** The latest report is kept under the machine's random agent
  id so it can be updated and deleted. That id also appears in the work ledger and, for a volunteer who linked credits to a player account,
  points to that account. A volunteer who wants nothing at all linked to them does not turn `--telemetry` on (nothing is sent by default).
  Making the stored report unlinkable too (a key that rotates every day) is possible and is listed under "Not handled yet".
- **Hardware and idle load are reported by each machine and not verified**; tokens are measured by the gateway.
- **Copies.** Anyone can keep a copy of a public page (a screenshot, an archive, a scraper). Leaving removes the machine from the next
  page (within about 30 seconds); it cannot recall copies.

## Choices

| | |
|---|---|
| Not take part | Do nothing: it is off by default |
| Take part | `agent.py ... --telemetry` (or on `join`). The agent says at every start exactly what it sends and to whom. `--telemetry-show` prints the exact report and sends nothing. It refuses a gateway address that is plain `http://` on another machine |
| Stop and delete | `agent.py ... --telemetry-off` deletes what the machine reported; a machine silent for 2 days is forgotten anyway |
| Operator turns it off | `leaderboard.enabled: false`: no page, and reports are refused |
| Operator raises the bar | `leaderboard.min_group` (larger is more anonymous), `leaderboard.hidden_hardware` |

## Volunteers see what players write

This matters more than the statistics. When a title sets `allow_volunteers`, **the text of the player's message and the studio's NPC
prompt are sent to a volunteer's computer**, and a volunteer's model answers it. The platform account, name and address are not sent.
The earlier design note that volunteers should get "no player chat" cannot hold for dialogue and is superseded by this page.

- The software cannot stop a volunteer's own model server (Ollama and others) from logging requests. The
  [volunteer terms](volunteer-terms.md) forbid keeping or reading them; that is a promise, not a technical control.
- A studio that turns this on has to **tell its players** (see the text below) and should not turn it on for a title aimed at children or
  one where players type personal details to characters. Floor nodes that the operator runs are the alternative.
- `allow_volunteers` is off unless a title sets it. Safety judges and the guard never use volunteers.

## Direct fallback to a public LLM

A studio can turn on the SDKs' `direct` option ([sdk.md](sdk.md#direct-fallback-to-a-public-llm-optional-off-by-default)). Then, when the gateway cannot
be reached, **the player's recent lines and the NPC's prompt go from the player's device straight to Pollinations**
(text.pollinations.ai, operated by Myceli.AI OÜ, Estonia) and the model provider behind it, with the player's IP address as part
of the connection. The operator's gateway sees none of it, so none of the gateway's checks, budgets or retention rules apply.
Under Pollinations' terms the studio is the controller and Pollinations the processor; there is no data processing agreement
unless the studio arranges one, and processing may happen outside the EEA. Pollinations' own privacy policy governs what it
keeps. A studio that turns this on must name Pollinations in its privacy policy (add it to the text below) and should not turn it
on for a title aimed at children. It is off unless the studio sets it.

## For studios: what to tell your players

Put something like this in your game's privacy policy and, where players first meet an NPC, in the game: *"Some characters in this game
answer using AI. What you type to them is sent to a service that may run it on computers of community volunteers or on cloud
servers. Do not type personal information. We do not send your account name to them. The volunteers have agreed not to keep or read
what they process, but we cannot technically stop them."* Drop the sentence about volunteers if your title does not allow them.

## Children

Dialogue is typed by players, so for a title aimed at children (or players below the age of digital consent in your markets) the safe
settings are no `allow_volunteers`, and whatever age gate and parental consent your law requires. The software has no age check. The
statistics contain no player data at all.

## Security measures that exist

Opt-in; telemetry only over `https://` (or this machine); a report limited to 16 KB and one per 20 seconds, and only from a machine that
registered or served a job; a minimum group size; no name field anywhere; hardware text cleaned and escaped, with a restrictive content
policy; no indexing, no framing; a short retention (2 days) for the stored report, purged daily; banned machines not counted; and every
control above has a self-check that fails without it.

## Not handled yet

- **The work ledger and credit records are never deleted automatically.** They are pseudonymous (an agent id) until a player links a
  machine, after which they point at a platform account. A retention period and an erase-on-request path need a decision (the credit audit
  window is 7 days) and code.
- **The stored statistics report is pseudonymous for up to 2 days** (see above). A daily rotating key would make it unlinkable to the
  ledger and to a player account; it adds moving parts and has not been built.
- **No export or erase endpoint for a person's data**; the operator uses the database.
- **No age gate, no consent record** beyond the opt-in action itself.
- **Transfers.** Volunteers can be anywhere, so player messages can cross borders. The operator has to assess that.
- **A data protection impact assessment** is likely needed before launch, and a legal entity, privacy contact and governing law have to be
  named: see DESIGN.md section 22 (open decision 5).
