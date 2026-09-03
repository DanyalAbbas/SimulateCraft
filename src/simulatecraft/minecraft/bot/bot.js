/**
 * SimulateCraft Mineflayer bot — Node.js IPC server
 *
 * Starts a Mineflayer bot, opens a TCP server on --ipc-port, and serves
 * JSON-RPC requests from the Python bridge.
 *
 * Install:  cd src/simulatecraft/minecraft/bot && npm install
 * Deps:     mineflayer, mineflayer-pathfinder, mineflayer-collectblock
 *
 * Protocol (newline-delimited JSON):
 *   Python → Node:  {"id":"<uuid>","method":"<name>","params":{...}}
 *   Node → Python:  {"id":"<uuid>","result":{...}}
 *                or {"id":"<uuid>","error":"<message>"}
 *   Node → Python (push):  {"event":"<name>","data":{...}}
 */

"use strict";

const net = require("net");
const mineflayer = require("mineflayer");
const { pathfinder, Movements, goals } = require("mineflayer-pathfinder");
const Vec3 = require("vec3");

// ---------------------------------------------------------------------------
// Parse CLI args
// ---------------------------------------------------------------------------
const args = (() => {
  const a = {};
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i].replace(/^--/, "");
    const val = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : true;
    a[key] = val;
  }
  return a;
})();

const MC_HOST = args.host || "localhost";
const MC_PORT = parseInt(args.port || "25565", 10);
const USERNAME = args.username || "SimBot";
const IPC_PORT = parseInt(args["ipc-port"] || "25570", 10);
const AUTH = args.auth || "offline";
const PASSWORD = args.password || undefined;
const VERSION = args.version || undefined;

// ---------------------------------------------------------------------------
// IPC server — accepts one persistent connection from Python
// ---------------------------------------------------------------------------
let ipcSocket = null;
const pendingEvents = [];

function sendToP(obj) {
  if (ipcSocket && !ipcSocket.destroyed) {
    ipcSocket.write(JSON.stringify(obj) + "\n");
    return true;
  }
  return false;
}

function pushEvent(eventName, data) {
  const msg = { event: eventName, data: data || {} };
  if (!sendToP(msg)) {
    pendingEvents.push(msg);
  }
}

function sendResult(id, result) {
  sendToP({ id, result });
}

function sendError(id, message) {
  sendToP({ id, error: String(message) });
}

const ipcServer = net.createServer((socket) => {
  console.log("[ipc] Python connected");
  ipcSocket = socket;
  while (pendingEvents.length) {
    sendToP(pendingEvents.shift());
  }

  let buffer = "";
  socket.on("data", (chunk) => {
    buffer += chunk.toString();
    const lines = buffer.split("\n");
    buffer = lines.pop(); // keep incomplete last line
    for (const line of lines) {
      if (!line.trim()) continue;
      let msg;
      try {
        msg = JSON.parse(line);
      } catch (e) {
        console.error("[ipc] bad JSON:", line.slice(0, 120));
        continue;
      }
      handleRPC(msg).catch((err) => {
        sendError(msg.id, err.message || String(err));
      });
    }
  });

  socket.on("close", () => {
    console.log("[ipc] Python disconnected");
    ipcSocket = null;
  });

  socket.on("error", (err) => {
    console.error("[ipc] socket error:", err.message);
  });
});

ipcServer.listen(IPC_PORT, "127.0.0.1", () => {
  console.log(`[ipc] Listening on 127.0.0.1:${IPC_PORT}`);
});

// ---------------------------------------------------------------------------
// Mineflayer bot
// ---------------------------------------------------------------------------
const botOptions = {
  host: MC_HOST,
  port: MC_PORT,
  username: USERNAME,
  auth: AUTH,
};
if (PASSWORD) botOptions.password = PASSWORD;
if (VERSION) botOptions.version = VERSION;

const bot = mineflayer.createBot(botOptions);
bot.loadPlugin(pathfinder);

bot.once("spawn", () => {
  console.log(`[bot] Spawned as ${bot.username}`);
  // Configure pathfinder movements
  const mcData = require("minecraft-data")(bot.version);
  const defaultMove = new Movements(bot, mcData);
  bot.pathfinder.setMovements(defaultMove);
  pushEvent("bot.spawned", {
    username: bot.username,
    position: _pos(),
    gameMode: bot.game && bot.game.gameMode,
  });
});

bot.on("chat", (username, message) => {
  pushEvent("chat", { sender: username, text: message });
});

bot.on("error", (err) => {
  console.error("[bot] error:", err.message);
  pushEvent("bot.error", { message: err.message });
});

bot.on("end", (reason) => {
  console.log("[bot] disconnected:", reason);
  pushEvent("bot.disconnected", { reason: String(reason || "socketClosed") });
  // Stay alive so Python can read the error over IPC instead of finding a dead port.
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function _pos() {
  const p = bot.entity && bot.entity.position;
  if (!p) return { x: 0, y: 0, z: 0 };
  return { x: +p.x.toFixed(2), y: +p.y.toFixed(2), z: +p.z.toFixed(2) };
}

function _blockList(radius) {
  // Sample interesting nearby blocks cheaply. A full radius^3 scan freezes the bot.
  const r = Math.min(Math.max(2, radius || 8), 8);
  const pos = bot.entity.position;
  const seen = new Map();
  const interesting = new Set([
    "oak_log", "birch_log", "spruce_log", "jungle_log", "acacia_log", "dark_oak_log",
    "cherry_log", "mangrove_log",
    "coal_ore", "iron_ore", "copper_ore", "gold_ore", "diamond_ore", "lapis_ore",
    "deepslate_coal_ore", "deepslate_iron_ore", "deepslate_copper_ore",
    "crafting_table", "furnace", "chest", "water", "lava",
    "oak_leaves", "grass_block", "dirt", "stone", "cobblestone", "sand",
  ]);

  for (let dx = -r; dx <= r; dx++) {
    for (let dy = -2; dy <= 2; dy++) {
      for (let dz = -r; dz <= r; dz++) {
        const block = bot.blockAt(pos.offset(dx, dy, dz));
        if (!block || block.name === "air" || block.name === "cave_air") continue;
        if (!interesting.has(block.name) && Math.abs(dx) + Math.abs(dy) + Math.abs(dz) > 3) {
          continue;
        }
        const key = block.name;
        const dist = Math.abs(dx) + Math.abs(dy) + Math.abs(dz);
        if (!seen.has(key) || seen.get(key).dist > dist) {
          seen.set(key, {
            name: block.name,
            x: Math.floor(pos.x) + dx,
            y: Math.floor(pos.y) + dy,
            z: Math.floor(pos.z) + dz,
            hardness: block.hardness,
            dist,
          });
        }
      }
    }
  }
  return Array.from(seen.values())
    .sort((a, b) => a.dist - b.dist)
    .slice(0, 24)
    .map(({ dist, ...rest }) => rest);
}

function _entityList(radius) {
  const result = [];
  for (const entity of Object.values(bot.entities)) {
    if (entity === bot.entity) continue;
    const dist = bot.entity.position.distanceTo(entity.position);
    if (dist > radius) continue;
    result.push({
      name: entity.username || entity.name || entity.type,
      entity_type: entity.type === "player" ? "player" : entity.type === "object" ? "item" : "mob",
      x: +entity.position.x.toFixed(2),
      y: +entity.position.y.toFixed(2),
      z: +entity.position.z.toFixed(2),
      distance: +dist.toFixed(2),
      health: entity.health || null,
    });
  }
  result.sort((a, b) => a.distance - b.distance);
  return result.slice(0, 12);
}

function _inventory() {
  return bot.inventory.items().map((item) => ({
    name: item.name,
    count: item.count,
    slot: item.slot,
  }));
}

function _craftable() {
  // Keep this tiny — scanning every recipe every tick is extremely expensive.
  const basics = ["stick", "crafting_table", "wooden_pickaxe", "wooden_axe", "torch", "furnace"];
  try {
    const mcData = require("minecraft-data")(bot.version);
    const recipes = [];
    for (const name of basics) {
      const item = mcData.itemsByName[name];
      if (!item) continue;
      const r = bot.recipesFor(item.id, null, 1, null);
      if (r && r.length > 0) {
        recipes.push({ item_name: name, count: 1, needs_table: false });
      }
    }
    return recipes;
  } catch {
    return [];
  }
}

// Vanilla-ish MapColor bases (Minecraft filled map).
const MAP_COLORS = {
  none: [0, 0, 0],
  grass: [127, 178, 56],
  sand: [247, 233, 163],
  wool: [199, 199, 199],
  fire: [255, 0, 0],
  ice: [160, 160, 255],
  metal: [167, 167, 167],
  plant: [0, 124, 0],
  snow: [255, 255, 255],
  clay: [164, 168, 184],
  dirt: [151, 109, 77],
  stone: [112, 112, 112],
  water: [64, 64, 255],
  wood: [143, 119, 72],
  quartz: [255, 252, 245],
  color_orange: [216, 127, 51],
  color_magenta: [178, 76, 216],
  color_light_blue: [102, 153, 216],
  color_yellow: [229, 229, 51],
  color_light_green: [127, 204, 25],
  color_pink: [242, 127, 165],
  color_gray: [76, 76, 76],
  color_light_gray: [153, 153, 153],
  color_cyan: [76, 127, 153],
  color_purple: [127, 63, 178],
  color_blue: [51, 76, 178],
  color_brown: [102, 76, 51],
  color_green: [102, 127, 51],
  color_red: [153, 51, 51],
  color_black: [25, 25, 25],
  gold: [250, 238, 77],
  diamond: [92, 219, 213],
  lapis: [74, 128, 255],
  emerald: [0, 217, 58],
  podzol: [129, 86, 49],
  nether: [112, 2, 0],
  terracotta_white: [209, 177, 161],
  terracotta_orange: [159, 82, 36],
  terracotta_magenta: [149, 87, 108],
  terracotta_light_blue: [112, 108, 138],
  terracotta_yellow: [186, 133, 36],
  terracotta_light_green: [103, 117, 53],
  terracotta_pink: [160, 77, 78],
  terracotta_gray: [57, 41, 35],
  terracotta_light_gray: [135, 107, 98],
  terracotta_cyan: [87, 92, 92],
  terracotta_purple: [122, 73, 88],
  terracotta_blue: [76, 62, 92],
  terracotta_brown: [76, 50, 35],
  terracotta_green: [76, 82, 42],
  terracotta_red: [142, 60, 46],
  terracotta_black: [37, 22, 16],
  crimson_nylium: [189, 48, 49],
  crimson_stem: [148, 63, 97],
  crimson_hyphae: [92, 25, 29],
  warped_nylium: [22, 126, 134],
  warped_stem: [58, 142, 140],
  warped_hyphae: [86, 44, 62],
  warped_wart_block: [20, 180, 133],
  deepslate: [100, 100, 100],
  raw_iron: [216, 175, 147],
  glow_lichen: [127, 167, 150],
};

function _mapColorName(blockName) {
  const n = blockName || "unknown";
  if (n === "unknown" || n === "air" || n === "cave_air" || n === "void_air") return "none";
  if (n.includes("water") || n.includes("kelp") || n.includes("seagrass") || n.includes("bubble")) return "water";
  if (n.includes("lava") || n.includes("fire") || n.includes("magma") || n.includes("torch")) return "fire";
  if (n.includes("ice") || n.includes("packed_ice") || n.includes("frosted")) return "ice";
  if (n.includes("snow") || n.includes("powder_snow")) return "snow";
  if (n.includes("sand") || n.includes("sandstone") || n.includes("birch")) return "sand";
  if (n.includes("grass") || n === "moss_block") return "grass";
  if (n.includes("leave") || n.includes("vine") || n.includes("fern") || n.includes("azalea") || n.includes("moss_carpet")) return "plant";
  if (n.includes("dirt") || n.includes("mud") || n.includes("farmland") || n.includes("rooted")) return "dirt";
  if (n.includes("podzol") || n.includes("mycelium")) return "podzol";
  if (n.includes("log") || n.includes("wood") || n.includes("plank") || n.includes("hyphae") || n.includes("bamboo")) return "wood";
  if (n.includes("gravel") || n.includes("andesite") || n.includes("cobble") || n.includes("stone") || n.includes("diorite") || n.includes("granite") || n.includes("tuff") || n.includes("calcite")) return "stone";
  if (n.includes("deepslate") || n.includes("basalt") || n.includes("blackstone")) return "deepslate";
  if (n.includes("ore") && n.includes("iron")) return "raw_iron";
  if (n.includes("ore") && n.includes("gold")) return "gold";
  if (n.includes("ore") && n.includes("diamond")) return "diamond";
  if (n.includes("ore") && n.includes("emerald")) return "emerald";
  if (n.includes("ore") && n.includes("lapis")) return "lapis";
  if (n.includes("ore")) return "stone";
  if (n.includes("netherrack") || n.includes("nether_brick") || n.includes("soul_sand") || n.includes("soul_soil")) return "nether";
  if (n.includes("crimson")) return "crimson_stem";
  if (n.includes("warped") && n.includes("wart")) return "warped_wart_block";
  if (n.includes("warped")) return "warped_stem";
  if (n.includes("end_stone") || n.includes("quartz") || n.includes("dripstone")) return "quartz";
  if (n.includes("clay") || n.includes("prismarine")) return "clay";
  if (n.includes("gold")) return "gold";
  if (n.includes("iron") || n.includes("cauldron") || n.includes("hopper")) return "metal";
  if (n.includes("terracotta") || n.includes("tuff")) return "terracotta_orange";
  if (n.includes("wool") || n.includes("concrete") || n.includes("calcite")) return "wool";
  return "stone";
}

function _shadeMapColor(rgb, brightness) {
  // Vanilla map brightness: 0=180, 1=220, 2=255, 3=135 out of 255
  const factors = [180, 220, 255, 135];
  const f = factors[brightness] / 255;
  return [
    Math.max(0, Math.min(255, Math.floor(rgb[0] * f))),
    Math.max(0, Math.min(255, Math.floor(rgb[1] * f))),
    Math.max(0, Math.min(255, Math.floor(rgb[2] * f))),
  ];
}

function _filledMap(originX, originZ, size) {
  const rgb = Buffer.alloc(size * size * 3);
  const heights = new Array(size * size);
  const ey = bot.entity && bot.entity.position ? Math.floor(bot.entity.position.y) : 64;
  const yTop = Math.min(ey + 20, 320);
  const yBot = Math.max(ey - 16, -64);
  let lastY = ey;

  for (let iz = 0; iz < size; iz++) {
    for (let ix = 0; ix < size; ix++) {
      const x = originX + ix + 0.5;
      const z = originZ + iz + 0.5;
      let name = "unknown";
      let hy = yBot;
      const startY = Math.min(yTop, lastY + 4);
      for (let y = startY; y >= yBot; y--) {
        const b = bot.blockAt(new Vec3(x, y, z), false);
        if (!b) continue;
        if (b.name === "air" || b.name === "cave_air" || b.name === "void_air") continue;
        name = b.name;
        hy = y;
        break;
      }
      lastY = hy;
      const i = iz * size + ix;
      heights[i] = hy;
      let color;
      if (name === "unknown") {
        color = [196, 178, 130]; // unexplored parchment
      } else {
        const base = MAP_COLORS[_mapColorName(name)] || MAP_COLORS.stone;
        let brightness = 1;
        if (iz > 0) {
          const north = heights[(iz - 1) * size + ix];
          if (hy > north) brightness = 2;
          else if (hy < north) brightness = 0;
        }
        color = _shadeMapColor(base, brightness);
      }
      rgb[i * 3] = color[0];
      rgb[i * 3 + 1] = color[1];
      rgb[i * 3 + 2] = color[2];
    }
  }

  return {
    origin_x: originX,
    origin_z: originZ,
    width: size,
    height: size,
    format: "rgb",
    pixels: rgb.toString("base64"),
  };
}

// ---------------------------------------------------------------------------
// RPC dispatch
// ---------------------------------------------------------------------------
async function handleRPC(msg) {
  const { id, method, params = {} } = msg;

  switch (method) {
    // ---- State ----
      case "get_state": {
      const p = _pos();
      const biome = bot.world
        ? (bot.world.getBiome && bot.world.getBiome(bot.entity.position)) || "unknown"
        : "unknown";
      sendResult(id, {
        position: p,
        yaw: +(bot.entity.yaw * (180 / Math.PI)).toFixed(1),
        pitch: +(bot.entity.pitch * (180 / Math.PI)).toFixed(1),
        on_ground: bot.entity.onGround,
        biome: String(biome),
        stats: {
          health: bot.health || 20,
          food: bot.food || 20,
          saturation: bot.foodSaturation || 5,
          experience_level: bot.experience ? bot.experience.level : 0,
          game_mode: (bot.game && bot.game.gameMode) || "survival",
          is_raining: bot.isRaining || false,
          time_of_day: bot.time ? bot.time.timeOfDay : 0,
        },
        inventory: _inventory(),
        equipped_item: bot.heldItem ? bot.heldItem.name : null,
        nearby_blocks: _blockList(params.block_radius || 6),
        nearby_entities: _entityList(params.entity_radius || 16),
        craftable: _craftable(),
      });
      break;
    }

    case "get_map": {
      const size = Math.min(Math.max(parseInt(params.size || 128, 10), 16), 128);
      const originX = Math.floor(params.origin_x);
      const originZ = Math.floor(params.origin_z);
      sendResult(id, _filledMap(originX, originZ, size));
      break;
    }

    // ---- Actions ----
    case "perform_action": {
      const action = params.action || {};
      await executeAction(id, action);
      break;
    }

    default:
      sendError(id, `Unknown method: ${method}`);
  }
}

async function executeAction(rpcId, action) {
  const kind = action.kind;
  try {
    switch (kind) {
      // Movement
      case "move": {
        const dir = action.direction || "forward";
        const sprint = action.sprint || false;
        bot.setControlState("sprint", sprint);
        bot.setControlState(dir, true);
        await sleep(250);
        bot.setControlState(dir, false);
        bot.setControlState("sprint", false);
        sendResult(rpcId, { ok: true });
        break;
      }

      case "jump":
        bot.setControlState("jump", true);
        await sleep(100);
        bot.setControlState("jump", false);
        sendResult(rpcId, { ok: true });
        break;

      case "sneak":
        bot.setControlState("sneak", action.enable !== false);
        sendResult(rpcId, { ok: true });
        break;

      case "look_at": {
        if (action.entity) {
          const target = Object.values(bot.entities).find(
            (e) => (e.username || e.name || "").toLowerCase() === action.entity.toLowerCase()
          );
          if (target) await bot.lookAt(target.position);
        } else if (action.x != null) {
          const Vec3 = require("vec3");
          await bot.lookAt(new Vec3(action.x, action.y, action.z));
        }
        sendResult(rpcId, { ok: true });
        break;
      }

      // World
      case "mine_block": {
        let block;
        if (action.x != null) {
          block = bot.blockAt(bot.entity.position.offset(
            action.x - Math.floor(bot.entity.position.x),
            action.y - Math.floor(bot.entity.position.y),
            action.z - Math.floor(bot.entity.position.z),
          ));
        } else if (action.block_name) {
          const mcData = require("minecraft-data")(bot.version);
          const itemId = mcData.blocksByName[action.block_name]?.id;
          block = itemId != null ? bot.findBlock({ matching: itemId, maxDistance: 6 }) : null;
        }
        if (!block) { sendResult(rpcId, { ok: false, reason: "block not found" }); break; }
        // Stop movement first — digging while pathfinding aborts with "Digging aborted".
        try { bot.pathfinder.setGoal(null); } catch (_) { /* no pathfinder */ }
        ["forward", "back", "left", "right", "sprint", "jump"].forEach((c) => {
          try { bot.setControlState(c, false); } catch (_) { /* ignore */ }
        });
        try {
          await bot.dig(block);
          sendResult(rpcId, { ok: true, mined: block.name });
        } catch (err) {
          sendResult(rpcId, { ok: false, reason: String(err.message || err) });
        }
        break;
      }

      case "place_block": {
        const mcData = require("minecraft-data")(bot.version);
        const item = bot.inventory.findInventoryItem(
          mcData.itemsByName[action.block_name]?.id, null
        );
        if (!item) { sendResult(rpcId, { ok: false, reason: "item not in inventory" }); break; }
        await bot.equip(item, "hand");
        const Vec3 = require("vec3");
        const refBlock = bot.blockAt(new Vec3(action.x, action.y - 1, action.z));
        if (!refBlock) { sendResult(rpcId, { ok: false, reason: "reference block missing" }); break; }
        await bot.placeBlock(refBlock, new Vec3(0, 1, 0));
        sendResult(rpcId, { ok: true });
        break;
      }

      case "use_item":
        if (action.x != null) {
          const Vec3 = require("vec3");
          const block = bot.blockAt(new Vec3(action.x, action.y, action.z));
          if (block) await bot.activateBlock(block);
        } else {
          await bot.activateItem();
        }
        sendResult(rpcId, { ok: true });
        break;

      case "activate_block": {
        const Vec3 = require("vec3");
        const block = bot.blockAt(new Vec3(action.x, action.y, action.z));
        if (!block) { sendResult(rpcId, { ok: false, reason: "block not found" }); break; }
        await bot.activateBlock(block);
        sendResult(rpcId, { ok: true });
        break;
      }

      // Inventory
      case "equip": {
        const mcData = require("minecraft-data")(bot.version);
        const itemData = mcData.itemsByName[action.item_name];
        if (!itemData) { sendResult(rpcId, { ok: false, reason: "unknown item" }); break; }
        const item = bot.inventory.findInventoryItem(itemData.id, null);
        if (!item) {
          sendResult(rpcId, {
            ok: false,
            reason: `item not in inventory: ${action.item_name}`,
          });
          break;
        }
        const dest = action.destination === "hand" ? "hand" : action.destination;
        try {
          await bot.equip(item, dest);
          sendResult(rpcId, { ok: true, equipped: item.name, destination: dest });
        } catch (err) {
          sendResult(rpcId, { ok: false, reason: String(err.message || err) });
        }
        break;
      }

      case "drop_item": {
        const mcData = require("minecraft-data")(bot.version);
        const itemData = mcData.itemsByName[action.item_name];
        if (!itemData) { sendResult(rpcId, { ok: false, reason: "unknown item" }); break; }
        const item = bot.inventory.findInventoryItem(itemData.id, null);
        if (!item) {
          sendResult(rpcId, {
            ok: false,
            reason: `item not in inventory: ${action.item_name}`,
          });
          break;
        }
        const count = Math.min(action.count || item.count, item.count);
        try {
          await bot.toss(item.type, item.metadata, count);
          sendResult(rpcId, { ok: true, dropped: item.name, count });
        } catch (err) {
          sendResult(rpcId, { ok: false, reason: String(err.message || err) });
        }
        break;
      }

      case "craft": {
        const mcData = require("minecraft-data")(bot.version);
        const itemData = mcData.itemsByName[action.item_name];
        if (!itemData) { sendResult(rpcId, { ok: false, reason: "unknown item" }); break; }
        const want = Math.max(1, action.count || 1);
        let table = null;
        if (action.use_crafting_table) {
          table = bot.findBlock({
            matching: mcData.blocksByName.crafting_table?.id,
            maxDistance: 4,
          });
          if (!table) {
            sendResult(rpcId, { ok: false, reason: "no crafting_table nearby" });
            break;
          }
        }
        // Prefer recipes the bot can actually afford right now.
        let recipes = bot.recipesFor(itemData.id, null, want, table);
        if (!recipes.length && !table) {
          // Retry with a nearby table in case the recipe needs a 3x3 grid.
          table = bot.findBlock({
            matching: mcData.blocksByName.crafting_table?.id,
            maxDistance: 4,
          });
          if (table) recipes = bot.recipesFor(itemData.id, null, want, table);
        }
        if (!recipes.length) {
          sendResult(rpcId, {
            ok: false,
            reason: `cannot craft ${action.item_name} (missing ingredients` +
              (table ? "" : " or need crafting_table") + ")",
          });
          break;
        }
        try {
          await bot.craft(recipes[0], want, table);
          sendResult(rpcId, { ok: true, crafted: action.item_name, count: want });
        } catch (err) {
          sendResult(rpcId, {
            ok: false,
            reason: String(err.message || err),
          });
        }
        break;
      }

      // Social
      case "chat":
        bot.chat(action.text || "");
        sendResult(rpcId, { ok: true });
        break;

      case "whisper":
        bot.chat(`/msg ${action.target} ${action.text || ""}`);
        sendResult(rpcId, { ok: true });
        break;

      // Navigation
      case "navigate_to": {
        const goal = new goals.GoalNear(action.x, action.y, action.z, 1);
        const timeout = Math.min((action.timeout_seconds || 8), 12) * 1000;
        try {
          await Promise.race([
            bot.pathfinder.goto(goal),
            new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), timeout)),
          ]);
          sendResult(rpcId, { ok: true });
        } catch (err) {
          bot.pathfinder.setGoal(null);
          sendResult(rpcId, { ok: false, reason: err.message });
        }
        break;
      }

      case "follow": {
        const targetEntity = Object.values(bot.entities).find(
          (e) => (e.username || e.name || "").toLowerCase() === (action.target || "").toLowerCase()
        );
        if (!targetEntity) { sendResult(rpcId, { ok: false, reason: "entity not found" }); break; }
        const followGoal = new goals.GoalFollow(targetEntity, action.min_distance || 2);
        const timeout = Math.min((action.timeout_seconds || 8), 12) * 1000;
        bot.pathfinder.setGoal(followGoal, true);
        await sleep(timeout);
        bot.pathfinder.setGoal(null);
        sendResult(rpcId, { ok: true });
        break;
      }

      // Meta
      case "wait":
        await sleep((action.ticks || 1) * 50); // 1 tick ≈ 50ms
        sendResult(rpcId, { ok: true });
        break;

      case "noop":
        sendResult(rpcId, { ok: true });
        break;

      default:
        sendError(rpcId, `Unknown action kind: ${kind}`);
    }
  } catch (err) {
    sendError(rpcId, err.message || String(err));
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
