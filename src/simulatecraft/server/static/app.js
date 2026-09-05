/* SimulateCraft live viewer — full-bleed pannable map + event rail.
   Protocol:
     server → client: event | state | map
     client → server: chat | control | map
*/

const canvas = document.getElementById("world");
const ctx = canvas.getContext("2d");
const viewport = document.getElementById("map-viewport");
const logEl = document.getElementById("event-log");
const statusEl = document.getElementById("status");
const tickEl = document.getElementById("tick-counter");
const speedEl = document.getElementById("speed-readout");
const coordEl = document.getElementById("coord-readout");
const targetSel = document.getElementById("chat-target");
const hudEl = document.getElementById("hud");
const agentCountEl = document.getElementById("agent-count");
const mapOverlay = document.getElementById("map-overlay");
const followBtn = document.getElementById("btn-follow");
const speedPreset = document.getElementById("speed-preset");

const TILE = 128;
const MIN_ZOOM = 1.5; // px per block
const MAX_ZOOM = 24;

let latestState = null;
let socket = null;
let reconnectDelay = 1000;
let activeFilter = "all";
let followAgents = true;
let homeX = 0;
let homeZ = 0;
let panLimit = 512;
let tileSize = TILE;
let camera = { x: 0, z: 0, zoom: 6 };
let tiles = new Map(); // "ox,oz" -> {canvas, origin_x, origin_z, width, height}
let pendingTiles = new Set();
let drag = null;
let needsDraw = true;
let pinMode = false;
let spawnPin = { x: null, z: null };

function setMapLoading(loading) {
  if (!mapOverlay) return;
  mapOverlay.hidden = !loading;
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${proto}://${location.host}/ws`);
  socket.onopen = () => {
    setStatus("running", "connected");
    reconnectDelay = 1000;
    if (tiles.size === 0) setMapLoading(true);
    requestVisibleTiles(true);
  };
  socket.onclose = () => {
    setStatus("stopped", "disconnected");
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 10000);
  };
  socket.onmessage = (msg) => {
    let data;
    try {
      data = JSON.parse(msg.data);
    } catch {
      return;
    }
    if (data.type === "event") handleEvent(data.event);
    else if (data.type === "state") applyState(data.state);
    else if (data.type === "map") ingestMap(data.map);
    else if (data.type === "agent_created") {
      setAgentFormStatus(`Spawned ${data.username} (${data.agent_id})`, false);
      addLogEntry(`spawned ${esc(data.agent_id)}`, -1, "system");
    } else if (data.type === "agent_deleted") {
      addLogEntry(`removed ${esc(data.agent_id)}`, -1, "system");
    }
  };
}

function send(obj) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(obj));
  }
}

function setStatus(state, label) {
  statusEl.dataset.state = state;
  statusEl.className = `status ${state}`;
  const labelEl = statusEl.querySelector(".status-label");
  if (labelEl) labelEl.textContent = label;
}

function formatTickRate(rate) {
  if (rate == null || rate <= 0) return "max";
  const n = Number(rate);
  if (Number.isInteger(n) || Math.abs(n - Math.round(n)) < 1e-9) return String(Math.round(n));
  return n.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

function syncSpeedPreset(rate) {
  if (!speedPreset) return;
  if (rate == null || rate <= 0) {
    speedPreset.value = "max";
    return;
  }
  const options = ["0.25", "0.5", "1", "2", "4", "8"];
  const match = options.find((v) => Math.abs(Number(v) - Number(rate)) < 0.001);
  if (match) speedPreset.value = match;
  else {
    // keep a free-form feel: temporarily add/select closest label without inventing options
    const closest = options.reduce((best, v) =>
      Math.abs(Number(v) - Number(rate)) < Math.abs(Number(best) - Number(rate)) ? v : best
    );
    speedPreset.value = closest;
  }
}

function applyState(state) {
  latestState = state;
  const status = state.status || {};
  const snap = state.snapshot || {};
  const world = snap.world || {};
  const tick = snap.tick ?? status.tick ?? 0;
  const maxTicks = status.max_ticks;
  tickEl.textContent =
    maxTicks != null && maxTicks > 0 ? `t=${tick} / ${maxTicks}` : `t=${tick}`;

  const rate = status.tick_rate;
  if (speedEl) {
    speedEl.textContent =
      rate == null || rate <= 0 ? "max tps" : `${formatTickRate(rate)} tps`;
  }
  syncSpeedPreset(rate);

  if (status.paused) setStatus("paused", "paused");
  else if (status.running) setStatus("running", "running");
  else if (socket && socket.readyState === WebSocket.OPEN) setStatus("running", "connected");

  if (Array.isArray(world.home_xz) && world.home_xz.length >= 2) {
    homeX = Number(world.home_xz[0]);
    homeZ = Number(world.home_xz[1]);
  }
  if (world.pan_limit != null) panLimit = Number(world.pan_limit) || panLimit;
  if (world.tile_size != null) tileSize = Number(world.tile_size) || tileSize;

  if (world.map && world.map.pixels) ingestMap(world.map);

  if (followAgents) {
    const center = agentCentroid(snap.agents || {});
    if (center) {
      camera.x = center[0];
      camera.z = center[1];
      clampCamera();
    }
  }

  updateAgentList(state);
  updateHud(state);
  updateCoordReadout();
  requestVisibleTiles(false);
  needsDraw = true;
}

function agentCentroid(agents) {
  const pts = [];
  for (const info of Object.values(agents)) {
    const p = info.position_3d || info.position;
    if (!p || p.length < 2) continue;
    const x = Number(p[0]);
    const z = Number(p.length > 2 ? p[2] : p[1]);
    pts.push([x, z]);
  }
  if (!pts.length) return null;
  return [
    pts.reduce((s, p) => s + p[0], 0) / pts.length,
    pts.reduce((s, p) => s + p[1], 0) / pts.length,
  ];
}

function tileKey(ox, oz) {
  return `${ox},${oz}`;
}

function ingestMap(map) {
  if (!map || !map.pixels) return;
  const w = Number(map.width || tileSize);
  const h = Number(map.height || tileSize);
  const ox = Math.floor(Number(map.origin_x));
  const oz = Math.floor(Number(map.origin_z));
  const key = tileKey(ox, oz);
  pendingTiles.delete(key);

  try {
    const raw = Uint8Array.from(atob(map.pixels), (c) => c.charCodeAt(0));
    const off = document.createElement("canvas");
    off.width = w;
    off.height = h;
    const octx = off.getContext("2d");
    const img = octx.createImageData(w, h);
    for (let i = 0; i < w * h; i++) {
      img.data[i * 4] = raw[i * 3];
      img.data[i * 4 + 1] = raw[i * 3 + 1];
      img.data[i * 4 + 2] = raw[i * 3 + 2];
      img.data[i * 4 + 3] = 255;
    }
    octx.putImageData(img, 0, 0);
    tiles.set(key, { canvas: off, origin_x: ox, origin_z: oz, width: w, height: h });
    setMapLoading(false);
    needsDraw = true;
  } catch (err) {
    console.warn("bad map tile", err);
  }
}

function visibleWorldBounds() {
  const halfW = (canvas.width / 2) / camera.zoom;
  const halfH = (canvas.height / 2) / camera.zoom;
  return {
    minX: camera.x - halfW,
    maxX: camera.x + halfW,
    minZ: camera.z - halfH,
    maxZ: camera.z + halfH,
  };
}

function requestVisibleTiles(force) {
  const b = visibleWorldBounds();
  const pad = tileSize * 0.25;
  const minTX = Math.floor((b.minX - pad) / tileSize) * tileSize;
  const maxTX = Math.floor((b.maxX + pad) / tileSize) * tileSize;
  const minTZ = Math.floor((b.minZ - pad) / tileSize) * tileSize;
  const maxTZ = Math.floor((b.maxZ + pad) / tileSize) * tileSize;

  for (let ox = minTX; ox <= maxTX; ox += tileSize) {
    for (let oz = minTZ; oz <= maxTZ; oz += tileSize) {
      if (!tileInPanBounds(ox, oz)) continue;
      const key = tileKey(ox, oz);
      if (!force && (tiles.has(key) || pendingTiles.has(key))) continue;
      pendingTiles.add(key);
      send({ type: "map", origin_x: ox, origin_z: oz, size: tileSize });
    }
  }
}

function tileInPanBounds(ox, oz) {
  // Allow tiles that intersect the allowed exploration square.
  const min = homeX - panLimit;
  const max = homeX + panLimit;
  const minZ = homeZ - panLimit;
  const maxZ = homeZ + panLimit;
  return ox + tileSize > min && ox < max && oz + tileSize > minZ && oz < maxZ;
}

function clampCamera() {
  camera.x = Math.max(homeX - panLimit, Math.min(homeX + panLimit, camera.x));
  camera.z = Math.max(homeZ - panLimit, Math.min(homeZ + panLimit, camera.z));
  camera.zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, camera.zoom));
}

function updateCoordReadout() {
  if (!coordEl) return;
  coordEl.textContent = `${camera.x.toFixed(0)}, ${camera.z.toFixed(0)}`;
}

function resizeCanvas() {
  if (!viewport) return;
  const rect = viewport.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(1, Math.floor(rect.width * dpr));
  const h = Math.max(1, Math.floor(rect.height * dpr));
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
    needsDraw = true;
  }
}

function worldToScreen(wx, wz) {
  return [
    canvas.width / 2 + (wx - camera.x) * camera.zoom,
    canvas.height / 2 + (wz - camera.z) * camera.zoom,
  ];
}

function screenToWorld(sx, sy) {
  return [
    camera.x + (sx - canvas.width / 2) / camera.zoom,
    camera.z + (sy - canvas.height / 2) / camera.zoom,
  ];
}

function draw() {
  resizeCanvas();
  if (!needsDraw && !drag) {
    requestAnimationFrame(draw);
    return;
  }
  needsDraw = false;

  ctx.fillStyle = "#c4a574";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Unexplored parchment grid
  ctx.save();
  ctx.strokeStyle = "rgba(90, 70, 50, 0.25)";
  ctx.lineWidth = 1;
  const b = visibleWorldBounds();
  const step = tileSize;
  const gx0 = Math.floor(b.minX / step) * step;
  const gz0 = Math.floor(b.minZ / step) * step;
  for (let x = gx0; x <= b.maxX; x += step) {
    const [sx] = worldToScreen(x, 0);
    ctx.beginPath();
    ctx.moveTo(sx, 0);
    ctx.lineTo(sx, canvas.height);
    ctx.stroke();
  }
  for (let z = gz0; z <= b.maxZ; z += step) {
    const [, sy] = worldToScreen(0, z);
    ctx.beginPath();
    ctx.moveTo(0, sy);
    ctx.lineTo(canvas.width, sy);
    ctx.stroke();
  }
  ctx.restore();

  // Pan limit border
  const [x0, y0] = worldToScreen(homeX - panLimit, homeZ - panLimit);
  const [x1, y1] = worldToScreen(homeX + panLimit, homeZ + panLimit);
  ctx.strokeStyle = "rgba(241, 194, 50, 0.55)";
  ctx.lineWidth = 2;
  ctx.setLineDash([8, 6]);
  ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
  ctx.setLineDash([]);

  ctx.imageSmoothingEnabled = false;
  for (const tile of tiles.values()) {
    const [sx, sy] = worldToScreen(tile.origin_x, tile.origin_z);
    const dw = tile.width * camera.zoom;
    const dh = tile.height * camera.zoom;
    if (sx > canvas.width || sy > canvas.height || sx + dw < 0 || sy + dh < 0) continue;
    ctx.drawImage(tile.canvas, sx, sy, dw, dh);
  }

  if (typeof window.customRenderer === "function" && latestState) {
    window.customRenderer(ctx, latestState, { camera, worldToScreen });
  } else if (latestState) {
    drawAgents(latestState);
  }

  updateSpawnPinMarker();
  requestAnimationFrame(draw);
}

function drawAgents(state) {
  const agents = (state.snapshot || {}).agents || {};
  for (const [id, info] of Object.entries(agents)) {
    const p = info.position_3d || info.position;
    if (!p || p.length < 2) continue;
    const wx = Number(p[0]);
    const wz = Number(p.length > 2 ? p[2] : p[1]);
    const [x, y] = worldToScreen(wx, wz);
    drawMapPointer(x, y, Number(info.yaw || 0), info.name || id);
  }
}

function drawMapPointer(x, y, yawDeg, name) {
  const rad = ((yawDeg + 180) * Math.PI) / 180;
  const s = Math.max(0.75, Math.min(1.6, camera.zoom / 6));
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(rad);
  ctx.scale(s, s);
  ctx.beginPath();
  ctx.moveTo(0, -9);
  ctx.lineTo(6, 8);
  ctx.lineTo(0, 4);
  ctx.lineTo(-6, 8);
  ctx.closePath();
  ctx.fillStyle = "#ffffff";
  ctx.strokeStyle = "#1a1a1a";
  ctx.lineWidth = 1.5;
  ctx.fill();
  ctx.stroke();
  ctx.restore();

  ctx.font = "600 12px Figtree, system-ui, sans-serif";
  ctx.textAlign = "center";
  const tw = ctx.measureText(name).width;
  ctx.fillStyle = "rgba(40, 28, 16, 0.78)";
  ctx.fillRect(x - tw / 2 - 3, y + 10 * s, tw + 6, 15);
  ctx.fillStyle = "#f5e6c8";
  ctx.fillText(name, x, y + 10 * s + 11);
}

function meter(kind, label, value, max = 20) {
  const pct = Math.max(0, Math.min(100, (Number(value) / max) * 100));
  return `
    <div class="meter ${kind}">
      <span class="meter-label">${label}</span>
      <div class="meter-bar"><span class="meter-fill" style="width:${pct}%"></span></div>
      <span class="meter-val">${Number(value).toFixed(0)}</span>
    </div>`;
}

function updateHud(state) {
  if (!hudEl) return;
  const agents = (state.snapshot || {}).agents || {};
  const entries = Object.entries(agents);
  if (agentCountEl) agentCountEl.textContent = String(entries.length);
  if (!entries.length) {
    hudEl.innerHTML = '<p class="empty">No agents yet — use Add agent.</p>';
    return;
  }
  hudEl.innerHTML = entries
    .map(([id, info]) => {
      const pos3 = info.position_3d;
      const pos = pos3
        ? `${Number(pos3[0]).toFixed(0)}, ${Number(pos3[1]).toFixed(0)}, ${Number(pos3[2]).toFixed(0)}`
        : "—";
      const health = info.health != null ? meter("health", "HP", info.health) : "";
      const food = info.food != null ? meter("food", "Food", info.food) : "";
      const holding = info.holding ? `Holding ${esc(info.holding)}` : "";
      const goal = info.goal ? `Goal · ${esc(info.goal)}` : "";
      const meta = [holding, goal].filter(Boolean).join(" · ");
      return `
        <article class="agent-row" data-agent-id="${esc(id)}">
          <div class="agent-main">
            <div class="agent-name">${esc(info.name || id)}</div>
            <div class="agent-pos">${esc(pos)}</div>
          </div>
          <div class="agent-stats">${health}${food}</div>
          ${meta ? `<div class="agent-meta">${meta}</div>` : ""}
          <button type="button" class="mc-btn agent-remove" data-remove="${esc(id)}" title="Remove agent">×</button>
        </article>`;
    })
    .join("");
  hudEl.querySelectorAll("[data-remove]").forEach((btn) => {
    btn.onclick = () => removeAgent(btn.getAttribute("data-remove"));
  });
}

function updateAgentList(state) {
  const current = new Set(Array.from(targetSel.options).map((o) => o.value));
  const agents = Object.keys((state.snapshot || {}).agents || {});
  for (const id of agents) {
    if (!current.has(id)) addAgentOption(id);
    current.delete(id);
  }
  for (const gone of current) {
    if (gone === "") continue;
    const opt = Array.from(targetSel.options).find((o) => o.value === gone);
    if (opt) opt.remove();
  }
}

function addAgentOption(id) {
  const opt = document.createElement("option");
  opt.value = id;
  opt.textContent = id;
  targetSel.appendChild(opt);
}

function handleEvent(ev) {
  switch (ev.kind) {
    case "agent.acted": {
      const ms = ev.decision_ms != null ? ` · ${Number(ev.decision_ms).toFixed(0)}ms` : "";
      addLogEntry(
        `<span class="who">${esc(ev.agent_id)}</span> <span class="act">${esc(ev.action_kind)}</span>${esc(ms)}`,
        ev.tick,
        "action"
      );
      break;
    }
    case "agent.spoke":
      addLogEntry(`<span class="who">${esc(ev.agent_id)}</span> “${esc(ev.text)}”`, ev.tick, "chat");
      break;
    case "human.chat":
      addLogEntry(
        `<span class="who">you${ev.target_agent_id ? " → " + esc(ev.target_agent_id) : ""}</span> ${esc(ev.text)}`,
        ev.tick,
        "human chat"
      );
      break;
    case "brain.failed":
      addLogEntry(`${esc(ev.agent_id)} brain failed: ${esc(ev.error)}`, ev.tick, "error system");
      break;
    case "agent.added":
      addLogEntry(`${esc(ev.agent_id)} joined`, ev.tick, "system");
      break;
    case "agent.removed":
      addLogEntry(`${esc(ev.agent_id)} left`, ev.tick, "system");
      break;
    case "simulation.started":
      addLogEntry(`simulation started (${(ev.agent_ids || []).length} agents)`, ev.tick, "system");
      break;
    case "simulation.ended":
      addLogEntry(`simulation ended: ${esc(ev.reason)}`, ev.tick, "system");
      break;
    case "simulation.paused":
      addLogEntry("paused", ev.tick, "system");
      break;
    case "simulation.resumed":
      addLogEntry("resumed", ev.tick, "system");
      break;
    default:
      break;
  }
}

function addLogEntry(html, tick, cls = "") {
  const div = document.createElement("div");
  div.className = `entry ${cls}`.trim();
  div.dataset.kinds = cls;
  div.innerHTML = `<span class="tick">t${tick >= 0 ? tick : ""}</span><span class="body">${html}</span>`;
  applyFilterToEntry(div);
  logEl.appendChild(div);
  while (logEl.children.length > 300) logEl.removeChild(logEl.firstChild);
  logEl.scrollTop = logEl.scrollHeight;
}

function applyFilterToEntry(el) {
  if (activeFilter === "all") {
    el.hidden = false;
    return;
  }
  el.hidden = !(el.dataset.kinds || "").split(/\s+/).includes(activeFilter);
}

function setFilter(filter) {
  activeFilter = filter;
  document.querySelectorAll(".filter").forEach((btn) => {
    const on = btn.dataset.filter === filter;
    btn.classList.toggle("is-active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
  logEl.querySelectorAll(".entry").forEach(applyFilterToEntry);
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = String(s ?? "");
  return d.innerHTML;
}

function setFollow(on) {
  followAgents = on;
  followBtn.classList.toggle("is-active", on);
  if (on && latestState) {
    const center = agentCentroid((latestState.snapshot || {}).agents || {});
    if (center) {
      camera.x = center[0];
      camera.z = center[1];
      clampCamera();
      updateCoordReadout();
      requestVisibleTiles(false);
      needsDraw = true;
    }
  }
}

function pointerToCanvas(evt) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  return [(evt.clientX - rect.left) * scaleX, (evt.clientY - rect.top) * scaleY];
}

viewport.addEventListener("pointerdown", (evt) => {
  if (evt.button !== 0) return;
  if (pinMode) {
    const [sx, sy] = pointerToCanvas(evt);
    const [wx, wz] = screenToWorld(sx, sy);
    setSpawnPin(wx, wz);
    setPinMode(false);
    evt.preventDefault();
    return;
  }
  viewport.setPointerCapture(evt.pointerId);
  const [sx, sy] = pointerToCanvas(evt);
  drag = { sx, sy, camX: camera.x, camZ: camera.z };
  viewport.classList.add("is-dragging");
  setFollow(false);
});

viewport.addEventListener("pointermove", (evt) => {
  if (!drag) return;
  const [sx, sy] = pointerToCanvas(evt);
  camera.x = drag.camX - (sx - drag.sx) / camera.zoom;
  camera.z = drag.camZ - (sy - drag.sy) / camera.zoom;
  clampCamera();
  updateCoordReadout();
  needsDraw = true;
});

function endDrag(evt) {
  if (!drag) return;
  drag = null;
  viewport.classList.remove("is-dragging");
  requestVisibleTiles(false);
  if (evt && viewport.hasPointerCapture?.(evt.pointerId)) {
    viewport.releasePointerCapture(evt.pointerId);
  }
}

viewport.addEventListener("pointerup", endDrag);
viewport.addEventListener("pointercancel", endDrag);

viewport.addEventListener(
  "wheel",
  (evt) => {
    evt.preventDefault();
    const [sx, sy] = pointerToCanvas(evt);
    const [beforeX, beforeZ] = screenToWorld(sx, sy);
    const factor = evt.deltaY > 0 ? 0.9 : 1.1;
    camera.zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, camera.zoom * factor));
    const [afterX, afterZ] = screenToWorld(sx, sy);
    camera.x += beforeX - afterX;
    camera.z += beforeZ - afterZ;
    clampCamera();
    updateCoordReadout();
    setFollow(false);
    requestVisibleTiles(false);
    needsDraw = true;
  },
  { passive: false }
);

window.addEventListener("resize", () => {
  needsDraw = true;
  requestVisibleTiles(false);
});

document.getElementById("btn-pause").onclick = () => send({ type: "control", command: "pause" });
document.getElementById("btn-play").onclick = () => send({ type: "control", command: "resume" });
document.getElementById("btn-step").onclick = () => send({ type: "control", command: "step", n: 1 });
document.getElementById("btn-step-10").onclick = () =>
  send({ type: "control", command: "step", n: 10 });
document.getElementById("btn-slower").onclick = () => send({ type: "control", command: "slower" });
document.getElementById("btn-faster").onclick = () => send({ type: "control", command: "faster" });
document.getElementById("btn-extend-ticks").onclick = () =>
  send({ type: "control", command: "extend_ticks", n: 1000 });

if (speedPreset) {
  speedPreset.addEventListener("change", () => {
    const v = speedPreset.value;
    if (v === "max") send({ type: "control", command: "set_tick_rate", value: 0 });
    else send({ type: "control", command: "set_tick_rate", value: Number(v) });
  });
}

followBtn.onclick = () => setFollow(!followAgents);

/* ---- Sidebar collapse ---- */
const stageEl = document.querySelector(".stage");
const STORAGE_KEY = "simulatecraft.sidebars";

function readSidebarPrefs() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { config: true, rail: true };
    const parsed = JSON.parse(raw);
    return {
      config: parsed.config !== false,
      rail: parsed.rail !== false,
    };
  } catch {
    return { config: true, rail: true };
  }
}

function writeSidebarPrefs(prefs) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    /* ignore */
  }
}

function applySidebars(prefs) {
  if (!stageEl) return;
  stageEl.classList.toggle("config-collapsed", !prefs.config);
  stageEl.classList.toggle("rail-collapsed", !prefs.rail);

  const tabConfig = document.getElementById("tab-open-config");
  const tabRail = document.getElementById("tab-open-rail");
  if (tabConfig) tabConfig.hidden = prefs.config;
  if (tabRail) tabRail.hidden = prefs.rail;

  const btnConfig = document.getElementById("btn-toggle-config");
  const btnRail = document.getElementById("btn-toggle-rail");
  if (btnConfig) {
    btnConfig.classList.toggle("is-off", !prefs.config);
    btnConfig.setAttribute("aria-pressed", String(!prefs.config));
    btnConfig.title = prefs.config ? "Hide configure panel" : "Show configure panel";
  }
  if (btnRail) {
    btnRail.classList.toggle("is-off", !prefs.rail);
    btnRail.setAttribute("aria-pressed", String(!prefs.rail));
    btnRail.title = prefs.rail ? "Hide chat panel" : "Show chat panel";
  }

  needsDraw = true;
  requestVisibleTiles(false);
}

let sidebarPrefs = readSidebarPrefs();
applySidebars(sidebarPrefs);

function setSidebar(which, open) {
  sidebarPrefs = { ...sidebarPrefs, [which]: open };
  writeSidebarPrefs(sidebarPrefs);
  applySidebars(sidebarPrefs);
}

function toggleSidebar(which) {
  setSidebar(which, !sidebarPrefs[which]);
}

document.querySelectorAll(".sidebar-close").forEach((btn) => {
  btn.addEventListener("click", () => setSidebar(btn.dataset.sidebar, false));
});
document.getElementById("btn-toggle-config")?.addEventListener("click", () => toggleSidebar("config"));
document.getElementById("btn-toggle-rail")?.addEventListener("click", () => toggleSidebar("rail"));
document.getElementById("tab-open-config")?.addEventListener("click", () => setSidebar("config", true));
document.getElementById("tab-open-rail")?.addEventListener("click", () => setSidebar("rail", true));

document.querySelectorAll(".filter").forEach((btn) => {
  btn.addEventListener("click", () => setFilter(btn.dataset.filter));
});

document.getElementById("chat-form").onsubmit = (e) => {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text) return;
  send({ type: "chat", text, target: targetSel.value || null });
  input.value = "";
};

const pinBtn = document.getElementById("btn-pin");
const spawnReadout = document.getElementById("spawn-readout");
const spawnPinEl = document.getElementById("spawn-pin");
const agentForm = document.getElementById("agent-form");
const agentFormStatus = document.getElementById("agent-form-status");

function setPinMode(on) {
  pinMode = on;
  if (pinBtn) pinBtn.classList.toggle("is-active", on);
  if (viewport) viewport.classList.toggle("is-pinning", on);
  if (on) setFollow(false);
}

function setSpawnPin(x, z) {
  spawnPin = { x: Math.round(x), z: Math.round(z) };
  const sx = document.getElementById("agent-spawn-x");
  const sz = document.getElementById("agent-spawn-z");
  if (sx) sx.value = String(spawnPin.x);
  if (sz) sz.value = String(spawnPin.z);
  if (spawnReadout) spawnReadout.textContent = `${spawnPin.x}, ${spawnPin.z}`;
  updateSpawnPinMarker();
}

function updateSpawnPinMarker() {
  if (!spawnPinEl) return;
  if (spawnPin.x == null || spawnPin.z == null) {
    spawnPinEl.hidden = true;
    return;
  }
  const [sx, sy] = worldToScreen(spawnPin.x, spawnPin.z);
  const rect = canvas.getBoundingClientRect();
  const scaleX = rect.width / canvas.width;
  const scaleY = rect.height / canvas.height;
  spawnPinEl.hidden = false;
  spawnPinEl.style.left = `${sx * scaleX}px`;
  spawnPinEl.style.top = `${sy * scaleY}px`;
}

function setAgentFormStatus(text, isError) {
  if (!agentFormStatus) return;
  if (!text) {
    agentFormStatus.hidden = true;
    return;
  }
  agentFormStatus.hidden = false;
  agentFormStatus.textContent = text;
  agentFormStatus.classList.toggle("is-error", !!isError);
}

async function removeAgent(agentId) {
  if (!agentId) return;
  try {
    const res = await fetch(`/api/agents/${encodeURIComponent(agentId)}`, { method: "DELETE" });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || res.statusText);
    }
  } catch (err) {
    addLogEntry(`remove failed: ${esc(err.message || err)}`, -1, "error system");
  }
}

if (pinBtn) {
  pinBtn.onclick = () => setPinMode(!pinMode);
}

if (agentForm) {
  async function spawnAgentFromForm() {
    const username = document.getElementById("agent-username").value.trim();
    if (!username) {
      setAgentFormStatus("Username is required", true);
      return;
    }
    const persona = document.getElementById("agent-persona").value.trim();
    const instructions = document.getElementById("agent-instructions").value.trim();
    const goal = document.getElementById("agent-goal").value.trim() || "survive and explore";
    const spawnY = Number(document.getElementById("agent-spawn-y").value);
    const payload = {
      username,
      persona: persona || `You are ${username}, a Minecraft adventurer.`,
      goal,
    };
    if (instructions) payload.instructions = instructions;
    if (spawnPin.x != null && spawnPin.z != null) {
      payload.spawn_x = spawnPin.x;
      payload.spawn_y = Number.isFinite(spawnY) ? spawnY : 64;
      payload.spawn_z = spawnPin.z;
    }
    const btn = document.getElementById("btn-spawn-agent");
    if (btn) btn.disabled = true;
    setAgentFormStatus("Spawning…", false);
    try {
      const res = await fetch("/api/agents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(apiErrorMessage(body, res.statusText));
      setAgentFormStatus(`Spawned ${body.username} (${body.agent_id})`, false);
      document.getElementById("agent-username").value = "";
    } catch (err) {
      setAgentFormStatus(String(err.message || err), true);
    } finally {
      if (btn) btn.disabled = false;
    }
  }
  agentForm.addEventListener("submit", (e) => {
    e.preventDefault();
    spawnAgentFromForm();
  });
  const spawnBtn = document.getElementById("btn-spawn-agent");
  if (spawnBtn) spawnBtn.addEventListener("click", (e) => {
    e.preventDefault();
    spawnAgentFromForm();
  });
}

const watcherForm = document.getElementById("watcher-form");
const watcherFormStatus = document.getElementById("watcher-form-status");

function setWatcherFormStatus(text, isError) {
  if (!watcherFormStatus) return;
  if (!text) {
    watcherFormStatus.hidden = true;
    return;
  }
  watcherFormStatus.hidden = false;
  watcherFormStatus.textContent = text;
  watcherFormStatus.classList.toggle("is-error", !!isError);
}

function apiErrorMessage(body, fallback) {
  const detail = body && body.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (item && (item.msg || item.message)) || JSON.stringify(item))
      .join("; ");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return fallback || "Request failed";
}

async function assignWatcherRole() {
  const usernameEl = document.getElementById("watcher-username");
  const roleEl = document.getElementById("watcher-role");
  const username = (usernameEl && usernameEl.value.trim()) || "";
  const role = (roleEl && roleEl.value) || "";
  if (!username) {
    setWatcherFormStatus("Enter your Minecraft username", true);
    return;
  }
  if (!role) {
    setWatcherFormStatus("Pick a role", true);
    return;
  }
  const btn = document.getElementById("btn-assign-role");
  if (btn) btn.disabled = true;
  setWatcherFormStatus("Assigning…", false);
  try {
    const res = await fetch("/api/watchers/role", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, role }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(apiErrorMessage(body, res.statusText));
    setWatcherFormStatus(body.message || `Assigned ${body.role} → ${body.username}`, false);
    addLogEntry(`watcher ${esc(body.username)} → ${esc(body.role)}`, -1, "system");
  } catch (err) {
    setWatcherFormStatus(String(err.message || err), true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

if (watcherForm) {
  watcherForm.addEventListener("submit", (e) => {
    e.preventDefault();
    assignWatcherRole();
  });
}
const assignBtn = document.getElementById("btn-assign-role");
if (assignBtn) {
  assignBtn.addEventListener("click", (e) => {
    e.preventDefault();
    assignWatcherRole();
  });
}

// Accordion: only one workshop open at a time in the config column.
document.querySelectorAll(".config-scroll .workshop").forEach((panel) => {
  panel.addEventListener("toggle", () => {
    if (!panel.open) return;
    document.querySelectorAll(".config-scroll .workshop").forEach((other) => {
      if (other !== panel) other.open = false;
    });
  });
});

window.addEventListener("keydown", (e) => {
  if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT")) {
    return;
  }
  if (e.code === "Space") {
    e.preventDefault();
    const paused = latestState && latestState.status && latestState.status.paused;
    send({ type: "control", command: paused ? "resume" : "pause" });
  } else if (e.key === ".") {
    send({ type: "control", command: "step", n: e.shiftKey ? 10 : 1 });
  } else if (e.key === "+" || e.key === "=") {
    send({ type: "control", command: "faster" });
  } else if (e.key === "-" || e.key === "_") {
    send({ type: "control", command: "slower" });
  } else if (e.key.toLowerCase() === "f") {
    setFollow(!followAgents);
  } else if (e.key === "Escape" && pinMode) {
    setPinMode(false);
  }
});

setFollow(true);
connect();
requestAnimationFrame(draw);
