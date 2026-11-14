// The main story, written by hand so that it holds together whatever the model says in each city: three acts, a boss
// each, and two endings. Pure data and small functions (no Phaser), tested by check.mjs.
//
// Act I   Cold Trail   Beat the Warden under Old Town and learn how the Directorate tracks every jump.
// Act II  The Relays   Every city hides a Directorate relay. Destroy three, in three different cities.
// Act III The Spire    The Director pulls you to his Spire. Beat him, then choose what happens to his archive.
//
// Dialogue lines are "text" or [speaker, "text"]; the speakers LEAD and MATE stand for the party, "" is the narrator.

export const RELAYS_NEEDED = 3;
export const ACTS = ["", "Act I: Cold Trail", "Act II: The Relays", "Act III: The Spire"];
export const ENDINGS = { burn: "Burn the archive", keep: "Keep the keys" };

/** What the companion says on first arriving somewhere new: one line for the climate or, for a harbour or river town, the water. */
const BANTER = {
  desert: ["Whose idea was it to wear a coat? The sand is in my boots already.", "Stay in the shade when you can. The Directorate can't track what it can't see through the glare.", "Funny. Everything out here is the same colour as our luck."],
  snow: ["Cold enough that my teeth are teleporting. Keep moving.", "Footprints. In snow. We might as well leave a map for them.", "Try not to blink-strike anything breakable. It's all ice."],
  tropical: ["I can't tell if that's rain or just the air. Either way, my coat is ruined.", "At least it's hard to be grim somewhere with this many flowers.", "Stick together. I don't trust anything that grows this fast."],
  temperate: ["Quiet streets. I don't trust quiet streets.", "Let's find someone who knows the place before we do anything clever.", "A normal town. For about ten minutes I'd like to pretend we live in one."],
  harbor: ["Smell the salt? Ships mean a way out, if it comes to that.", "Piers are bad places to be cornered. Stay near the street.", "Look at all those barrels. Somebody's smuggling something. Not our problem."],
  river: ["Only one bridge. I'd rather we weren't on it when the Directorate shows up.", "A river splits a town in two. People here must gossip across it.", "Hear the water? Good cover for talking."],
};
export function banter(climate, style, seed) {
  const pool = style === "harbor" || style === "river" ? [...BANTER[style], ...BANTER[climate]] : BANTER[climate] || BANTER.temperate;
  return pool[seed % pool.length];
}

export const newPlot = () => ({ act: 1, relays: [], spire: false, ending: null });

/** Notes a destroyed relay (one per city). Returns {count, last}: how many are down, and whether that was the one that ends Act II. */
export function destroyRelay(plot, city) {
  if (!plot.relays.includes(city)) plot.relays.push(city);
  return { count: plot.relays.length, last: plot.relays.length >= RELAYS_NEEDED };
}

/** What the player should be doing now, in one or two sentences (the Story page of the menu). */
export function objective(plot) {
  if (plot.act <= 1) return "Go through the gate in the north-east of Old Town, down into the Undercroft, and defeat the Warden.";
  if (plot.act === 2) return `Destroy the Directorate's relays: ${plot.relays.length} of ${RELAYS_NEEDED} are down. Open the menu, choose Teleport, and find the pulsing red light in a city. Each city has one.`;
  if (plot.ending) return "The Directorate is finished. Explore, or teleport anywhere.";
  return "The Director is waiting at the heart of the Spire. Open the menu and choose Teleport, then Directorate Spire, if you need to get back.";
}

/** A sentence for the NPCs' prompts, so that what they say fits how far along the story is. */
export function situation(plot, isHome) {
  if (plot.act <= 1) return isHome ? " The Directorate's Warden guards the Undercroft." : "";
  if (plot.act === 2) return ` They have defeated the Warden and are destroying the Directorate's relays (${plot.relays.length} of ${RELAYS_NEEDED} so far).`;
  return plot.ending ? " They have brought down the Director and the Directorate." : " They have destroyed the Directorate's relays, and the Director is expected to strike.";
}

const ALL_DOWN = [
  ["", "The last relay dies. Every red light in every city goes dark at once."],
  ["Agent Kessler", "Well done. You have made the Director very interested."],
  ["Agent Kessler", "He would like to meet you in person. Do not bother jumping away. This time we are bringing you."],
  ["", "The air folds around you, and you are somewhere else."],
];

export const BEATS = {
  bossIntro: {
    warden: ["The jumper, at last. The Directorate does not ask twice.", "Come quietly, or come in pieces."],
    director: [["The Director", "Forty-one jumps, and you never once asked why you could do it."],
      ["The Director", "Because I made you. The Waypoint program was mine, and so are you."],
      ["LEAD", "We were never yours."],
      ["The Director", "Then let me take back what I lent you."]],
  },
  wardenWon: [
    ["LEAD", "That's the Warden down."],
    ["", "A cracked tablet flickers on the floor. JUMP LOG: 41 jumps, 41 traces. RELAYS: 3 ACTIVE."],
    ["MATE", "Every jump leaves a thread. The Directorate has relays in cities all over the world, listening for them."],
    ["LEAD", "Then we cut them. Three of them, anywhere on Earth. Look for a red light."],
    ["", "Act II. Open the menu (Esc), choose Teleport and name any real place. Every city hides a relay."],
  ],
  relayDark: "A Directorate device is bolted to the wall, humming. Its light is dark. Whatever it is, it is not listening to you yet.",
  relayDead: "The relay here is only wreckage now. Nothing listens.",
  relayFound: city => [["", `A Directorate relay hums in ${city}, its red eye turning towards you.`], ["MATE", "It's tracing our jump. Break it before it calls anyone!"]],
  relayDown: (n, city) => (n >= RELAYS_NEEDED ? ALL_DOWN : [
    ["", `The relay shorts out in a shower of sparks. Relays down: ${n} of ${RELAYS_NEEDED}.`],
    ["LEAD", `${city} is off their map. ${RELAYS_NEEDED - n} more.`]]),
  spireArrive: [
    ["MATE", "This is where all the traces lead. A tower in the middle of nowhere."],
    ["LEAD", "Floor after floor of relays. Whatever he wants us for, it ends here."],
    ["", "Dormant Directorate pads glow here and there. Step up to one and press confirm to restore the party."],
  ],
  directorWon: [
    ["The Director", "Fold... me... back..."],
    ["", "The Director falls, and the Spire shudders. His archive lies open: a file on every jumper, and the keys to every relay on Earth."],
    ["MATE", "It's all here. Every trace, every name."],
    ["LEAD", "So what do we do with it?"],
  ],
  endings: {
    burn: [["", "You feed the files to the Spire's furnace, and the keys after them. The relays go dead for good."],
      ["MATE", "No one can follow a jump again."], ["LEAD", "And no one can find us by one. That will do."]],
    keep: [["", "You take the keys. Every relay on Earth now answers to you."],
      ["MATE", "Nobody will chase us now."], ["LEAD", "No. Perhaps we are the ones who decide who gets chased."]],
  },
};

/** The epilogue to show if the gateway cannot write one. */
export function epilogueFallback(ending, cities) {
  const route = cities.length ? `${cities.slice(0, 4).join(", ")} still remember two strangers who came and went` : "The towns they passed through remember two strangers who came and went";
  return ending === "keep"
    ? `${route}, and a quiet voice on every relay that never says who is listening. The jumpers were never chased again.`
    : `${route} without a trace. The Directorate's files burned for three days, and nobody has been tracked by a jump since.`;
}
