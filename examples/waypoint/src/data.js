// Maps and dialogue for the vertical slice. Positions are in 32px tiles.

// Pieces baked by tools/build_tiles.py. foot: the solid part [x, y, w, h] in pixels from the top-left (null: walk-through).
export const STAMPS = {
  house: { w: 96, h: 192, foot: [0, 100, 96, 92] }, // the roof overhangs: walking behind it hides you, like the SNES games
  tree: { w: 96, h: 160, foot: [34, 124, 28, 18] },
  pine: { w: 96, h: 192, foot: [34, 156, 28, 18] },
  gate: { w: 32, h: 64, foot: [0, 0, 32, 64] },
  chest: { w: 32, h: 32, foot: [2, 8, 28, 24] },
  dungeon_wall: { w: 96, h: 128, foot: null, flat: true },
};

export const MAPS = {
  town: {
    name: "Old Town", w: 40, h: 26, ground: "grass", battle: "town",
    paint: [["cobble", 11, 7, 18, 9], ["cobble", 18, 16, 4, 1], ["sidewalk", 0, 16, 40, 1], ["sidewalk", 0, 19, 40, 1], ["cobble", 18, 16, 4, 1], ["road_line", 0, 17, 40, 1], ["road", 0, 18, 40, 1], ["cobble", 29, 10, 4, 4]],
    objects: [
      ["house", 4, 1], ["house", 9, 1], ["house", 14, 1], ["house", 23, 1], ["house", 28, 1], ["house", 33, 1],
      ["house", 6, 19], ["house", 27, 19],
      ["tree", 0, 7], ["tree", 0, 11], ["pine", 36, 6], ["pine", 36, 10], ["tree", 12, 19], ["pine", 17, 19], ["tree", 21, 19],
      ["pine", 0, 19], ["tree", 34, 19], ["gate", 31, 8],
    ],
    labels: [["Undercroft", 31.5, 7.6]],
    npcs: [
      { id: "shopkeeper", x: 15, y: 7, dir: "down", talk: "shop" },
      { id: "local_f", x: 21, y: 12, dir: "down", talk: "ines" },
      { id: "agent", x: 33, y: 11, dir: "left", talk: "agent" },
    ],
    zones: [{ x: 31, y: 10, w: 1, h: 1, go: { map: "undercroft", x: 3, y: 6 } }],
    spawn: [19, 12],
    intro: "arrived",
  },
  undercroft: {
    name: "The Undercroft", w: 30, h: 18, ground: "flagstone", battle: "dungeon",
    paint: [
      ["brick", 0, 0, 30, 3, true], ["brick", 0, 17, 30, 1, true], ["brick", 0, 0, 1, 18, true], ["brick", 29, 0, 1, 18, true],
      ["brick", 8, 3, 1, 9, true], ["brick", 15, 7, 1, 10, true], ["brick", 22, 3, 1, 9, true],
    ],
    objects: [["dungeon_wall", 1, -1], ["dungeon_wall", 10, -1], ["dungeon_wall", 17, -1], ["dungeon_wall", 24, -1],
      ["chest", 5, 15, { chest: "c1", item: "ether", n: 2 }], ["chest", 18, 4, { chest: "c2", item: "potion", n: 3 }]],
    boss: { x: 26, y: 9, enemy: "minotaur_mage", flag: "warden" },
    labels: [["▲ Old Town", 2.5, 3.2]],
    zones: [
      { x: 1, y: 3, w: 3, h: 1, go: { map: "town", x: 31, y: 11 } },
      { x: 24, y: 7, w: 1, h: 6, boss: true },
    ],
    encounters: [["bat", "bat"], ["slime"], ["snake", "bat"], ["eyeball", "slime"], ["spider_bot"], ["drone_tank"], ["snake", "snake", "bat"], ["slime", "eyeball", "slime"]],
    spawn: [3, 6],
  },
};

// Dialogue: lines are "text" (spoken by the NPC) or [speaker, "text"]; LEAD and MATE stand for the party.
export const TALK = {
  arrived: [["MATE", "So this is where we landed. Quiet little town."], ["LEAD", "Too quiet. Someone has been following our jumps."],
    ["MATE", "Let's ask around. Esc or X opens the menu if you need it."]],
  ines: { before: ["The old tram tunnels run under the town. Men in grey suits go down there at night.", "If you're heading down, buy potions from Tobias first."],
    after: ["The suits are gone! I don't know what you did, but thank you."] },
  agent: { before: ["You must be the jumper. The Directorate has a job offer for you.", "Folding space is wasted on errands for shopkeepers. Work for us.",
    "Our Warden waits in the Undercroft. Go and see what refusing us costs."],
    after: ["...You broke the Warden.", "The Director will hear of this. Blink wherever you like. We will be there first."] },
  shop: ["Welcome to Tobias' Provisions! What'll it be?"],
  warden: ["The jumper, at last. The Directorate does not ask twice.", "Come quietly, or come in pieces."],
  won: [["LEAD", "That's the Warden down. They'll only send more."], ["MATE", "Then we'd better be somewhere else when they do."],
    ["", "End of the vertical slice. Thanks for playing! You can keep exploring."]],
};
