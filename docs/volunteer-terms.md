# Volunteer terms (draft)

> **Draft for counsel review. Not legal advice.** These are the terms a person accepts before running the node agent. The operator must
> adapt them, fill in the [BRACKETS], and show them (or a link) where the volunteer starts the agent. The agent prints a short notice
> at every start and links here.

**Operator:** [OPERATOR NAME AND ADDRESS]. **Contact:** [CONTACT]. **Applicable law and courts:** [JURISDICTION].

## 1. What you are agreeing to run

The node agent connects **out** to the operator's gateway (it opens no port on your computer), asks for work, and passes each job to
a model server on your own machine (Ollama, llama-server, vLLM or similar). It forwards only `/v1/chat/completions` requests. You can
read its code. You can stop it at any time with Ctrl+C or by closing it; there is no minimum uptime.

## 2. Who can volunteer

You must be of the age of majority where you live (at least 18) and entitled to use the computer, its power and its network. Do not run
it on a computer that belongs to an employer, school or other person without their permission, or on rented cloud machines you do not
control. You are responsible for following the licence of the model you run.

## 3. What you will handle, and what you promise

Jobs contain **text that players typed to game characters**, and the studio's instructions to those characters. Players may type
personal things. You promise that you will not:

- keep, copy, log, read, sell, share or analyse job text or the model's answers, other than what your model server does in memory to
  answer. Turn off request logging in your model server where it has one, and delete anything captured by accident;
- try to find out who a player is, or contact one;
- change an answer, return answers from a different model than the one you declare, or answer without running the model;
- run more than one identity or machine to earn more credits than your hardware earns, fake a node, or interfere with the checks
  (known-answer probes run now and then; failing them can get you banned).

Tell the operator if you learn that job text was exposed.

## 4. Your resources

You pay for your own electricity, bandwidth and wear. The agent pauses while you use the computer (by default above 60 percent CPU or
GPU), but it makes no promise that your computer will stay cool, quiet or fast; you run it at your own risk. Check that your cooling and
power supply cope with sustained load.

## 5. Credits

Credits are a virtual reward for work done. They have no cash value, are not property, cannot be sold or transferred, and can be spent
only on items the participating games offer. New credit is held for 7 days. If you are banned inside that window, credit still on hold is
void. The operator sets the rate per token and the items, may change either, and does not promise that credits will always be
spendable. No money, cryptocurrency or other payment is made.

## 6. Anonymous statistics (optional, separate)

By default nothing about your computer is sent. If you start the agent with `--telemetry`, it sends your CPU model, GPU models and
memory, an operating system name and a slow average of your idle GPU load, with **no name, account or address**. The gateway publishes only
statistics about groups of machines with the same hardware (never a single machine, and nothing at all until enough machines report),
and keeps your latest report under the agent's random id for up to 2 days so it can update it. The agent says exactly this at every
start, `--telemetry-show` prints the exact report, and `--telemetry-off` deletes it. Copies of a public page can exist outside the
operator's control. The details, including how anonymous this is and is not, are in [privacy.md](privacy.md).

## 7. Suspension and bans

The operator can pause, ban or block your agent or token if it fails verification, breaks section 3, is abused or is a risk to others.
A ban ends your credits that are still on hold. You may stop at any time.

## 8. Your data

What the operator keeps about you, why, and for how long is in [privacy.md](privacy.md): an agent id, the tokens you served, your
verification results, and, if you link a machine to a player account or opt in to the leaderboard, those links and details.

## 9. About the answers

The answers are produced by the model on your computer for a game. The gateway checks them before a player sees them, but do not rely
on that. You are not the publisher of the game or its characters.

## 10. No warranty, limits

To the extent the law allows, the agent and the service are provided as they are, without promises of availability, earnings or
fitness, and the operator is not liable for loss or damage to your computer, data or income, or for anything a game or player does. This
does not limit rights the law gives you as a consumer or liability the law does not allow to be limited.

## 11. Changes and ending

The operator may change these terms with notice [HOW]; continuing to run the agent after a change means you accept it. You can stop at
any time, and `--telemetry-off` removes your leaderboard details. Sections 3, 5 (void credit), 8 and 10 continue after you stop.
