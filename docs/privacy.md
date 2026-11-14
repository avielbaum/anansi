# Privacy: what Anansi collects, shows and keeps

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
| Platform account id (for example a Steam id), tokens used per day | Player | Daily token budget, so one account cannot use everything | `retention_days` (35), then deleted |
| The text of a player's message and the NPC's reply | Player | Not stored: processed in memory by the gateway and sent to whichever model answers (see below). The operator's own logging or proxy may differ | Not stored by the gateway |
| A random agent id, tokens and jobs served per day, probe results, bans | Volunteer | Verification and the work ledger | The ledger has no automatic deletion (see "Not handled yet") |
| A link between an agent id and a player's account, earned and spent credits | Volunteer / player | Volunteer credits | While credits exist (no automatic deletion) |
| **Leaderboard, machine (opt-in)**: display name, CPU model, thread count, GPU models and memory, operating system name, a slow average of idle GPU load, time of the last report | Volunteer | Public leaderboard | Until the volunteer leaves (`--telemetry-off`), is blocked, or stays silent for `retention_days` |
| **Leaderboard, player (opt-in)**: display name, linked to the account | Player | Public leaderboard | Until the player sets an empty name, or is blocked |
| Leaderboard blocks: the hash shown on the board or the name, and the date | Volunteer / player | Moderation | Until lifted |

Nothing about a computer other than the list above is read: no hostname, user name, address, serial number, driver version or file.

## What is public

The leaderboard (`/leaderboard`, `/v1/leaderboard`) shows, only for machines and players that chose to be listed:

- **Machines:** rank, display name, a short hash of the agent id, CPU and GPU models with memory, operating system name, a typical idle GPU
  figure in whole percent, tokens processed (today, 7 days, all time), jobs, and the date of the last report.
- **Players:** rank, display name, number of linked machines, tokens processed by those machines since they were linked.

It never shows the agent id, the platform account, an address, a hostname, a time of day, or which machines belong to which player.
Things to know before opting in:

- **The two lists can be matched.** A player with one machine and a machine with the same totals are the same person's. Anyone can see
  that. Opting in as both reveals the link; opting in as only one does not.
- **Hardware and idle load are reported by each machine and are not checked.** Tokens are measured by the gateway.
- **The idle figure is a slow average** (hours), not a live reading, so it does not show when the owner is using the computer.
- **A name is public text.** Do not use a real name. Links, email addresses, handles and phone numbers are refused, and the operator can
  block a name. A name is cleaned (invisible and right-to-left characters removed, 24 characters at most).
- **Copies.** The page asks search engines not to index it and cannot be framed by other sites, but anyone can keep a copy (a screenshot,
  an archive, a scraper). Leaving removes the entry within about 30 seconds (the page is cached that long); it cannot recall copies.

## Choices

| | |
|---|---|
| Not appear at all | Do nothing: both are off by default |
| Machine on | `agent.py ... --telemetry [--name NAME]` (or the same flags on `join`). The agent prints, at every start, what it sends and to whom, and `--telemetry-show` prints the exact report without sending anything. It refuses a gateway address that is plain `http://` on another machine |
| Machine off | `agent.py ... --telemetry-off` removes it and deletes what it reported |
| Player on / off | The game calls `set_leaderboard_name` with a name / an empty name |
| Operator removes someone | `POST /admin/leaderboard/block` with `{"node": "<hash>"}` or `{"user": "<name>"}`. It comes off the board at once and cannot be listed again; the volunteer still serves jobs and the player still plays |
| Operator turns it off | `leaderboard.enabled: false` (no page, no reports) or `leaderboard.players: false` (machines only) |

## Volunteers see what players write

This matters more than the leaderboard. When a title sets `allow_volunteers`, **the text of the player's message and the studio's NPC
prompt are sent to a volunteer's computer**, and a volunteer's model answers it. The platform account, name and address are not sent.
The earlier design note that volunteers should get "no player chat" cannot hold for dialogue and is superseded by this page.

- The software cannot stop a volunteer's own model server (Ollama and others) from logging requests. The
  [volunteer terms](volunteer-terms.md) forbid keeping or reading them; that is a promise, not a technical control.
- A studio that turns this on has to **tell its players** (see the text below) and should not turn it on for a title aimed at children or
  one where players type personal details to characters. Floor nodes that the operator runs are the alternative.
- `allow_volunteers` is off unless a title sets it. Safety judges and the guard never use volunteers.

## For studios: what to tell your players

Put something like this in your game's privacy policy and, where players first meet an NPC, in the game: *"Some characters in this game
answer using AI. What you type to them is sent to a service that may run it on computers of community volunteers or on cloud
servers. Do not type personal information. We do not send your account name to them. The volunteers have agreed not to keep or read
what they process, but we cannot technically stop them."* Drop the sentence about volunteers if your title does not allow them.

## Children

Leaderboard names are free text shown to the public, and dialogue is typed by players. For a title aimed at children (or players below the
age of digital consent in your markets) the safe settings are `leaderboard.players: false`, no `allow_volunteers`, and whatever age gate
and parental consent your law requires. The software has no age check.

## Security measures that exist

Opt-in for both sides; telemetry only over `https://` (or this machine); the volunteer's report limited to 16 KB and one per 20 seconds,
and only from a machine that registered or served a job; everything outside written text cleaned and escaped on the page, with a
restrictive content policy; no indexing, no framing; links, emails and phone numbers refused in names; operator block and removal; a
daily purge of inactive reports; banned machines are not ranked; every protection above has a self-check that fails without it.

## Not handled yet

- **The work ledger and credit records are never deleted automatically.** They are pseudonymous (an agent id) until a player links a
  machine, after which they point at a platform account. A retention period and an erase-on-request path need a decision (the credit audit
  window is 7 days) and code.
- **No export or erase endpoint for a person's data**; the operator uses the database.
- **No age gate, no consent record** beyond the opt-in action itself.
- **Transfers.** Volunteers can be anywhere, so player messages can cross borders. The operator has to assess that.
- **A data protection impact assessment** is likely needed before launch, and a legal entity, privacy contact and governing law have to be
  named: see DESIGN.md section 22 (open decision 5).
