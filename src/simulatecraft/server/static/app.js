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
const MIN_ZOOM = 0.15; // px per block — low enough to frame multi-km squares
const MAX_ZOOM = 24;
const DRAW_VIEW_LIMIT = 8192; // match server map_pan_limit cap

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
let tiles = new Map(); // "ox,oz" -> locked terrain tile (never unloaded once loaded)
let pendingTiles = new Set();
let lastNearRefresh = 0;
let drag = null;
let needsDraw = true;
let pinMode = false;
let boundDrawMode = false;
let boundPins = []; // 4 square corners {x,z} when set
let mapPreloadBusy = false;
let boundClosed = false;
let boundAnchor = null; // first corner while drawing
let boundCursor = null; // world {x,z} while drawing
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
    else if (data.type === "map_preload_progress") {
      const cur = Number(data.current) || 0;
      const tot = Number(data.total) || 0;
      const phase = cur > tot * 0.99 && tot > 0 && cur !== tot
        ? "Filling gaps"
        : "Preloading map";
      // When mop-up runs, tot includes gap retries (e.g. 400+12).
      setStatus("boundaries-status", `${phase}… ${cur}/${tot}`, false);
    } else if (data.type === "map_preload_done") {
      mapPreloadBusy = false;
      if (data.pan_limit != null) panLimit = Number(data.pan_limit) || panLimit;
      const scanned = data.scanned ?? data.tiles ?? 0;
      const workers = data.workers != null ? ` · ${data.workers} bots` : "";
      const gaps = Number(data.gaps_retried) || 0;
      const gapNote = gaps > 0 ? ` · ${gaps} gap retries` : "";
      setStatus(
        "boundaries-status",
        `Map preloaded (${scanned} tile${scanned === 1 ? "" : "s"}${workers}${gapNote})`,
        false,
      );
      // Kick any remaining parchment tiles for another passive scan.
      for (const tile of tiles.values()) {
        if (!tile.loaded) tile.scannedAt = 0;
      }
      requestVisibleTiles(true);
      needsDraw = true;
    } else if (data.type === "map_preload_error") {
      mapPreloadBusy = false;
      setStatus("boundaries-status", String(data.error || "Preload failed"), true);
    } else if (data.type === "agent_created") {
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

function syncPlayPauseButtons(paused) {
  const play = document.getElementById("btn-play");
  const pause = document.getElementById("btn-pause");
  if (!play || !pause) return;
  const isPaused = !!paused;
  play.hidden = !isPaused;
  pause.hidden = isPaused;
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
  syncPlayPauseButtons(!!status.paused);

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

  // Only re-request empty/parchment tiles near agents so they can upgrade once.
  queueParchmentUpgrade(snap.agents || {});

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
  if (!map) return;
  const ox = Math.floor(Number(map.origin_x ?? NaN));
  const oz = Math.floor(Number(map.origin_z ?? NaN));
  if (Number.isFinite(ox) && Number.isFinite(oz)) {
    pendingTiles.delete(tileKey(ox, oz));
  }
  if (!map.pixels) {
    if (tiles.size === 0 && pendingTiles.size === 0) setMapLoading(false);
    return;
  }
  const w = Number(map.width || tileSize);
  const h = Number(map.height || tileSize);
  const key = tileKey(ox, oz);
  const coverage = Number(map.coverage);
  const hasCoverage = Number.isFinite(coverage);
  const cov = hasCoverage ? coverage : 0;
  // Loaded = enough real terrain; locked forever after that.
  const loaded = hasCoverage && cov >= 0.15;
  const existing = tiles.get(key);

  // Once loaded, never unload or replace.
  if (existing && existing.loaded) return;
  // Don't replace a placeholder with a worse/equal empty scan.
  if (existing && !loaded && cov <= (existing.coverage || 0)) return;

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
    tiles.set(key, {
      canvas: off,
      origin_x: ox,
      origin_z: oz,
      width: w,
      height: h,
      coverage: cov,
      loaded,
      scannedAt: Date.now(),
    });
    setMapLoading(false);
    needsDraw = true;
  } catch (err) {
    console.warn("bad map tile", err);
  }
}

/** Upgrade parchment placeholders near agents; never touch loaded tiles. */
function queueParchmentUpgrade(agents) {
  const now = Date.now();
  if (now - lastNearRefresh < 8000) return;
  lastNearRefresh = now;
  const pts = [];
  for (const info of Object.values(agents || {})) {
    const p = info.position_3d || info.position;
    if (!p || p.length < 2) continue;
    pts.push([Number(p[0]), Number(p.length > 2 ? p[2] : p[1])]);
  }
  if (!pts.length) return;
  const radius = tileSize * 1.5;
  let queued = 0;
  for (const [key, tile] of tiles.entries()) {
    if (tile.loaded) continue;
    if (pendingTiles.has(key)) continue;
    if (now - (tile.scannedAt || 0) < 8000) continue;
    const cx = tile.origin_x + tile.width / 2;
    const cz = tile.origin_z + tile.height / 2;
    const near = pts.some(([x, z]) => Math.abs(x - cx) <= radius && Math.abs(z - cz) <= radius);
    if (!near) continue;
    pendingTiles.add(key);
    send({ type: "map", origin_x: tile.origin_x, origin_z: tile.origin_z, size: tileSize });
    queued += 1;
    if (queued >= 3) break;
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
  const MAX_PENDING = 6;
  const now = Date.now();

  for (let ox = minTX; ox <= maxTX; ox += tileSize) {
    for (let oz = minTZ; oz <= maxTZ; oz += tileSize) {
      if (!tileInPanBounds(ox, oz)) continue;
      const key = tileKey(ox, oz);
      const existing = tiles.get(key);
      // Skip solid terrain; re-scan parchment after a cooldown (chunks may load later).
      if (existing && existing.loaded) continue;
      if (existing && !force && now - (existing.scannedAt || 0) < 12000) continue;
      if (pendingTiles.has(key)) continue;
      if (pendingTiles.size >= MAX_PENDING) return;
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

/** How far the camera may travel from home (blocks). Wider while drawing a square. */
function viewPanLimit() {
  let lim = panLimit;
  if (boundDrawMode) lim = Math.max(lim, DRAW_VIEW_LIMIT);
  if (boundPins.length >= 4) {
    const xs = boundPins.map((p) => p.x);
    const zs = boundPins.map((p) => p.z);
    const reach = Math.max(
      Math.abs(Math.min(...xs) - homeX),
      Math.abs(Math.max(...xs) - homeX),
      Math.abs(Math.min(...zs) - homeZ),
      Math.abs(Math.max(...zs) - homeZ),
    );
    lim = Math.max(lim, Math.ceil(reach) + 128);
  }
  return lim;
}

function clampCamera() {
  const lim = viewPanLimit();
  camera.x = Math.max(homeX - lim, Math.min(homeX + lim, camera.x));
  camera.z = Math.max(homeZ - lim, Math.min(homeZ + lim, camera.z));
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
  // Coarsen grid when zoomed out so we don't stroke tens of thousands of lines.
  let step = tileSize;
  const span = Math.max(b.maxX - b.minX, b.maxZ - b.minZ);
  while (span / step > 80) step *= 2;
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

  // Pan limit border — skip when enormous (huge strokeRect lags the GPU
  // without showing more terrain; radius only unlocks panning).
  const borderPx = panLimit * 2 * camera.zoom;
  if (borderPx > 0 && borderPx < Math.max(canvas.width, canvas.height) * 6) {
    const [x0, y0] = worldToScreen(homeX - panLimit, homeZ - panLimit);
    const [x1, y1] = worldToScreen(homeX + panLimit, homeZ + panLimit);
    ctx.strokeStyle = "rgba(241, 194, 50, 0.55)";
    ctx.lineWidth = 2;
    ctx.setLineDash([8, 6]);
    ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    ctx.setLineDash([]);
  }

  ctx.imageSmoothingEnabled = false;
  for (const tile of tiles.values()) {
    const [sx, sy] = worldToScreen(tile.origin_x, tile.origin_z);
    const dw = tile.width * camera.zoom;
    const dh = tile.height * camera.zoom;
    if (sx > canvas.width || sy > canvas.height || sx + dw < 0 || sy + dh < 0) continue;
    ctx.drawImage(tile.canvas, sx, sy, dw, dh);
  }

  // Play-area boundaries (shade outside after tiles so the mask is visible)
  drawBoundaries(latestState);

  if (typeof window.customRenderer === "function" && latestState) {
    window.customRenderer(ctx, latestState, { camera, worldToScreen });
  } else if (latestState) {
    drawAgents(latestState);
  }

  updateSpawnPinMarker();
  updateCornerPinMarkers();
  requestAnimationFrame(draw);
}

/** Axis-aligned square pinned at first corner ``a``, growing toward ``b``. */
function squareFromTwoCorners(a, b) {
  const dx = b.x - a.x;
  const dz = b.z - a.z;
  const side = Math.max(Math.abs(dx), Math.abs(dz), 1);
  const x1 = a.x + (dx >= 0 ? side : -side);
  const z1 = a.z + (dz >= 0 ? side : -side);
  const minX = Math.round(Math.min(a.x, x1));
  const maxX = Math.round(Math.max(a.x, x1));
  const minZ = Math.round(Math.min(a.z, z1));
  const maxZ = Math.round(Math.max(a.z, z1));
  return [
    { x: minX, z: minZ },
    { x: maxX, z: minZ },
    { x: maxX, z: maxZ },
    { x: minX, z: maxZ },
  ];
}

function boundSquareCornersFromSettings(b) {
  if (b.min_x != null && b.max_x != null && b.min_z != null && b.max_z != null) {
    return [
      { x: Math.round(b.min_x), z: Math.round(b.min_z) },
      { x: Math.round(b.max_x), z: Math.round(b.min_z) },
      { x: Math.round(b.max_x), z: Math.round(b.max_z) },
      { x: Math.round(b.min_x), z: Math.round(b.max_z) },
    ];
  }
  const src =
    Array.isArray(b.corners) && b.corners.length >= 2
      ? b.corners
      : Array.isArray(b.vertices) && b.vertices.length >= 2
        ? b.vertices
        : null;
  if (!src) return [];
  const xs = src.map((c) => Number(c.x));
  const zs = src.map((c) => Number(c.z));
  return squareFromTwoCorners(
    { x: Math.min(...xs), z: Math.min(...zs) },
    { x: Math.max(...xs), z: Math.max(...zs) },
  );
}

function drawBoundaries(state) {
  const world = (state && state.snapshot && state.snapshot.world) || {};
  const b = world.boundaries || {};
  let verts = boundPins.length >= 4 ? boundPins : [];
  if (!verts.length && !boundDrawMode) {
    verts = boundSquareCornersFromSettings(b);
  }
  // Rubber-band preview while placing the second corner.
  if (boundDrawMode && boundAnchor && boundCursor) {
    verts = squareFromTwoCorners(boundAnchor, boundCursor);
  }
  const closed = boundPins.length >= 4 && boundClosed;
  const showClosed =
    closed ||
    (!boundDrawMode && !!b.enabled && verts.length >= 4);
  const enabled = boundPins.length >= 4
    ? !!document.getElementById("bound-enabled")?.checked || closed
    : !!b.enabled;

  if (!verts.length && !boundDrawMode) return;

  ctx.save();
  const screenPts = verts.map((p) => worldToScreen(p.x, p.z));

  if (showClosed && enabled && screenPts.length >= 4) {
    ctx.beginPath();
    ctx.rect(0, 0, canvas.width, canvas.height);
    ctx.moveTo(screenPts[0][0], screenPts[0][1]);
    for (let i = 1; i < screenPts.length; i++) {
      ctx.lineTo(screenPts[i][0], screenPts[i][1]);
    }
    ctx.closePath();
    ctx.fillStyle = "rgba(8, 6, 4, 0.55)";
    ctx.fill("evenodd");
  }

  if (screenPts.length >= 1) {
    ctx.beginPath();
    ctx.moveTo(screenPts[0][0], screenPts[0][1]);
    for (let i = 1; i < screenPts.length; i++) {
      ctx.lineTo(screenPts[i][0], screenPts[i][1]);
    }
    ctx.closePath();
    const preview = boundDrawMode && boundAnchor;
    ctx.strokeStyle = preview
      ? "rgba(241, 194, 50, 0.9)"
      : "rgba(139, 195, 74, 0.95)";
    ctx.lineWidth = 2;
    ctx.setLineDash(preview ? [6, 4] : []);
    ctx.stroke();
    ctx.setLineDash([]);
    if (!preview && showClosed) {
      ctx.fillStyle = "rgba(93, 156, 61, 0.08)";
      ctx.fill();
    }
  }

  if (boundDrawMode && boundAnchor) {
    const [ax, ay] = worldToScreen(boundAnchor.x, boundAnchor.z);
    ctx.beginPath();
    ctx.arc(ax, ay, 4, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(241, 194, 50, 0.95)";
    ctx.fill();
  }
  ctx.restore();
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
      syncPlayPauseButtons(true);
      break;
    case "simulation.resumed":
      addLogEntry("resumed", ev.tick, "system");
      syncPlayPauseButtons(false);
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
  if (boundDrawMode) {
    const [sx, sy] = pointerToCanvas(evt);
    const [wx, wz] = screenToWorld(sx, sy);
    const x = Math.round(wx);
    const z = Math.round(wz);
    if (!boundAnchor) {
      boundAnchor = { x, z };
      boundPins = [];
      boundClosed = false;
      setStatus("boundaries-status", "Click opposite corner to finish the square", false);
    } else {
      boundPins = squareFromTwoCorners(boundAnchor, { x, z });
      boundClosed = true;
      boundAnchor = null;
      boundCursor = null;
      setBoundDrawMode(false);
      const en = document.getElementById("bound-enabled");
      if (en) en.checked = true;
      updateBoundReadout();
      updateCornerPinMarkers();
      setStatus("boundaries-status", "Square set — Build border to apply worldborder", false);
    }
    needsDraw = true;
    evt.preventDefault();
    return;
  }
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
  if (boundDrawMode) {
    const [sx, sy] = pointerToCanvas(evt);
    const [wx, wz] = screenToWorld(sx, sy);
    boundCursor = { x: Math.round(wx), z: Math.round(wz) };
    needsDraw = true;
  }
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

  async function generateAgentPrompt() {
    const username = document.getElementById("agent-username").value.trim();
    const draft = document.getElementById("agent-draft").value.trim();
    const existing = document.getElementById("agent-persona").value.trim();
    const text = draft || existing;
    if (!text) {
      setAgentFormStatus("Add draft notes (or a rough persona) first", true);
      return;
    }
    const useLlm = !!document.getElementById("agent-prompt-llm")?.checked;
    const btn = document.getElementById("btn-generate-prompt");
    if (btn) btn.disabled = true;
    setAgentFormStatus(useLlm ? "Generating prompt…" : "Building prompt…", false);
    try {
      const res = await fetch("/api/agents/generate-prompt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text,
          name: username || null,
          use_llm: useLlm,
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(apiErrorMessage(body, res.statusText));
      document.getElementById("agent-persona").value = body.persona || "";
      setAgentFormStatus(
        body.source === "llm" ? "Prompt generated (LLM)" : "Prompt generated (template)",
        false,
      );
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
  const genBtn = document.getElementById("btn-generate-prompt");
  if (genBtn) genBtn.addEventListener("click", (e) => {
    e.preventDefault();
    generateAgentPrompt();
  });
}

const bulkAgentsForm = document.getElementById("bulk-agents-form");
const bulkAgentsStatus = document.getElementById("bulk-agents-status");

function setBulkAgentsStatus(text, isError) {
  if (!bulkAgentsStatus) return;
  if (!text) {
    bulkAgentsStatus.hidden = true;
    return;
  }
  bulkAgentsStatus.hidden = false;
  bulkAgentsStatus.textContent = text;
  bulkAgentsStatus.classList.toggle("is-error", !!isError);
}

async function uploadBulkAgents() {
  const input = document.getElementById("bulk-agents-file");
  if (!input?.files?.length) {
    setBulkAgentsStatus("Choose a CSV or Excel file first", true);
    return;
  }
  const fd = new FormData();
  fd.append("file", input.files[0]);
  const params = new URLSearchParams();
  if (spawnPin.x != null && spawnPin.z != null) {
    const spawnY = Number(document.getElementById("agent-spawn-y")?.value);
    params.set("spawn_x", String(spawnPin.x));
    params.set("spawn_y", String(Number.isFinite(spawnY) ? spawnY : 64));
    params.set("spawn_z", String(spawnPin.z));
  }
  const qs = params.toString();
  const btn = document.getElementById("btn-bulk-agents");
  if (btn) btn.disabled = true;
  setBulkAgentsStatus("Uploading & spawning…", false);
  try {
    const res = await fetch(`/api/agents/bulk${qs ? `?${qs}` : ""}`, {
      method: "POST",
      body: fd,
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(apiErrorMessage(body, res.statusText));
    const n = (body.created || []).length;
    const errN = (body.errors || []).length;
    const bits = [`Spawned ${n} of ${body.total_rows || n}`];
    if (errN) bits.push(`${errN} failed`);
    setBulkAgentsStatus(bits.join(" · "), errN > 0 && n === 0);
    if (errN && body.errors?.[0]?.error) {
      addLogEntry(`bulk import: ${esc(body.errors[0].name || "?")}: ${esc(body.errors[0].error)}`, -1, "error system");
    }
    input.value = "";
  } catch (err) {
    setBulkAgentsStatus(String(err.message || err), true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

if (bulkAgentsForm) {
  const bulkBtn = document.getElementById("btn-bulk-agents");
  if (bulkBtn) bulkBtn.addEventListener("click", (e) => {
    e.preventDefault();
    uploadBulkAgents();
  });
}

const WORKSHOP_ROLES = [
  "name",
  "goal",
  "persona",
  "skin_url",
  "notes",
  "attribute",
  "trait",
  "skip",
];

let workshopColumns = [];

function setWorkshopStatus(text, isError) {
  const el = document.getElementById("workshop-status");
  if (!el) return;
  if (!text) {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  el.textContent = text;
  el.classList.toggle("is-error", !!isError);
}

function applyWorkshopToUi(body) {
  const instructions = document.getElementById("workshop-prompt-instructions");
  if (instructions) instructions.value = body.prompt_generator_instructions || "";
  workshopColumns = Array.isArray(body.roster_columns) ? body.roster_columns.map((c) => ({ ...c })) : [];
  renderWorkshopColumns();
  const hint = document.getElementById("bulk-expected-headers");
  if (hint) hint.textContent = body.expected_headers || "Name";
}

function renderWorkshopColumns() {
  const root = document.getElementById("workshop-columns");
  if (!root) return;
  root.innerHTML = "";
  workshopColumns.forEach((col, idx) => {
    const row = document.createElement("div");
    row.className = "workshop-column-row";
    row.dataset.idx = String(idx);
    const roleOpts = WORKSHOP_ROLES.map(
      (r) => `<option value="${r}" ${col.role === r ? "selected" : ""}>${r}</option>`,
    ).join("");
    row.innerHTML = `
      <div class="workshop-column-grid">
        <label>Key<input data-field="key" type="text" value="${esc(col.key || "")}" maxlength="64" /></label>
        <label>Label<input data-field="label" type="text" value="${esc(col.label || "")}" maxlength="120" /></label>
        <label>Headers<input data-field="headers" type="text" value="${esc((col.headers || []).join(", "))}" placeholder="Name, Username" /></label>
        <label>Role<select data-field="role">${roleOpts}</select></label>
      </div>
      <div class="workshop-column-actions">
        <label class="check-row"><input data-field="include_in_persona" type="checkbox" ${col.include_in_persona !== false ? "checked" : ""} /> In persona</label>
        <label class="check-row"><input data-field="identity" type="checkbox" ${col.identity ? "checked" : ""} /> Identity</label>
        <button type="button" class="mc-btn" data-action="remove">Remove</button>
      </div>
    `;
    root.appendChild(row);
  });
}

function readWorkshopColumnsFromDom() {
  const root = document.getElementById("workshop-columns");
  if (!root) return workshopColumns;
  const prevByKey = Object.fromEntries(
    (workshopColumns || []).map((c) => [c.key, c]),
  );
  const rows = [...root.querySelectorAll(".workshop-column-row")];
  return rows.map((row) => {
    const get = (field) => row.querySelector(`[data-field="${field}"]`);
    const headersRaw = get("headers")?.value || "";
    const key = (get("key")?.value || "").trim();
    const prev = prevByKey[key] || {};
    return {
      key,
      label: (get("label")?.value || "").trim(),
      headers: headersRaw.split(",").map((s) => s.trim()).filter(Boolean),
      role: get("role")?.value || "attribute",
      include_in_persona: !!get("include_in_persona")?.checked,
      identity: !!get("identity")?.checked,
      identity_format: prev.identity_format || "{value}",
    };
  }).filter((c) => c.key);
}

async function loadWorkshopSettings() {
  try {
    const res = await fetch("/api/agents/workshop");
    if (!res.ok) return;
    const body = await res.json();
    applyWorkshopToUi(body);
  } catch {
    /* ignore */
  }
}

async function saveWorkshopSettings() {
  const instructions = document.getElementById("workshop-prompt-instructions")?.value || "";
  const payload = {
    prompt_generator_instructions: instructions,
    roster_preset: "custom",
    roster_columns: readWorkshopColumnsFromDom(),
  };
  setWorkshopStatus("Saving…", false);
  try {
    const res = await fetch("/api/agents/workshop", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(apiErrorMessage(body, res.statusText));
    applyWorkshopToUi(body);
    setWorkshopStatus("Saved", false);
  } catch (err) {
    setWorkshopStatus(String(err.message || err), true);
  }
}

async function applyWorkshopPreset(name) {
  setWorkshopStatus(`Loading ${name}…`, false);
  try {
    const res = await fetch(`/api/agents/workshop/preset/${encodeURIComponent(name)}`, {
      method: "POST",
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(apiErrorMessage(body, res.statusText));
    applyWorkshopToUi(body);
    setWorkshopStatus(`Preset: ${name}`, false);
  } catch (err) {
    setWorkshopStatus(String(err.message || err), true);
  }
}

document.getElementById("btn-workshop-save")?.addEventListener("click", (e) => {
  e.preventDefault();
  saveWorkshopSettings();
});
document.getElementById("btn-workshop-add-column")?.addEventListener("click", (e) => {
  e.preventDefault();
  workshopColumns = readWorkshopColumnsFromDom();
  workshopColumns.push({
    key: `field_${workshopColumns.length + 1}`,
    label: "",
    headers: [],
    role: "attribute",
    include_in_persona: true,
    identity: false,
    identity_format: "{value}",
  });
  renderWorkshopColumns();
});
document.getElementById("btn-workshop-preset-university")?.addEventListener("click", (e) => {
  e.preventDefault();
  applyWorkshopPreset("university");
});
document.getElementById("btn-workshop-preset-minimal")?.addEventListener("click", (e) => {
  e.preventDefault();
  applyWorkshopPreset("minimal");
});
document.getElementById("workshop-columns")?.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-action='remove']");
  if (!btn) return;
  const row = btn.closest(".workshop-column-row");
  const idx = Number(row?.dataset.idx);
  workshopColumns = readWorkshopColumnsFromDom();
  if (Number.isFinite(idx)) workshopColumns.splice(idx, 1);
  renderWorkshopColumns();
});

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

// ---- World settings (rules / boundaries / import) ------------------------
let worldSettingsCache = null;

function setStatus(elId, text, isError) {
  const el = document.getElementById(elId);
  if (!el) return;
  el.hidden = !text;
  el.textContent = text || "";
  el.classList.toggle("is-error", !!isError);
}

function fillWorldForms(settings) {
  worldSettingsCache = settings;
  const r = settings.rules || {};
  const b = settings.boundaries || {};
  const w = settings.world || {};
  const setCheck = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.checked = !!val;
  };
  const setVal = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.value = val == null ? "" : String(val);
  };
  setCheck("rule-allow-night", r.allow_night !== false);
  setCheck("rule-daylight-cycle", r.daylight_cycle !== false);
  setVal("rule-day-length", r.day_length_minutes);
  setVal("rule-time-of-day", r.time_of_day || "keep");
  setCheck("rule-weather-cycle", r.weather_cycle !== false);
  setCheck("rule-clear-weather", r.clear_weather !== false);
  setCheck("rule-mob-spawning", r.do_mob_spawning !== false);
  setCheck("rule-hostile-mobs", r.hostile_mobs !== false);
  setCheck("rule-mob-griefing", !!r.mob_griefing);
  setCheck("rule-keep-inventory", r.keep_inventory !== false);
  setCheck("rule-fire-spreads", !!r.fire_spreads);
  setCheck("bound-enabled", !!b.enabled);
  setVal("bound-wall-y", b.wall_y_min ?? 60);
  setVal("bound-wall-h", b.wall_height ?? 16);
  setVal("bound-min-x", b.min_x ?? -64);
  setVal("bound-max-x", b.max_x ?? 64);
  setVal("bound-min-z", b.min_z ?? -64);
  setVal("bound-max-z", b.max_z ?? 64);
  setVal("bound-enforce", b.enforce || "soft");
  if (b.enabled) {
    boundPins = boundSquareCornersFromSettings(b);
    boundClosed = boundPins.length >= 4;
  } else {
    boundPins = [];
    boundClosed = false;
  }
  boundAnchor = null;
  updateBoundReadout();
  updateCornerPinMarkers();
  const label = document.getElementById("world-import-label");
  if (label) label.textContent = `Active: ${w.label || "Default"} (${w.source || "default"})`;
}

async function loadWorldSettings() {
  try {
    const res = await fetch("/api/world/settings");
    if (!res.ok) return;
    fillWorldForms(await res.json());
  } catch (_) {}
}

function readRulesFromForm() {
  const dayLen = document.getElementById("rule-day-length")?.value;
  return {
    allow_night: !!document.getElementById("rule-allow-night")?.checked,
    daylight_cycle: !!document.getElementById("rule-daylight-cycle")?.checked,
    day_length_minutes: dayLen === "" || dayLen == null ? null : Number(dayLen),
    time_of_day: document.getElementById("rule-time-of-day")?.value || "keep",
    weather_cycle: !!document.getElementById("rule-weather-cycle")?.checked,
    clear_weather: !!document.getElementById("rule-clear-weather")?.checked,
    do_mob_spawning: !!document.getElementById("rule-mob-spawning")?.checked,
    hostile_mobs: !!document.getElementById("rule-hostile-mobs")?.checked,
    mob_griefing: !!document.getElementById("rule-mob-griefing")?.checked,
    keep_inventory: !!document.getElementById("rule-keep-inventory")?.checked,
    fire_spreads: !!document.getElementById("rule-fire-spreads")?.checked,
  };
}

function syncBoundFieldsFromPins() {
  if (!boundPins.length) return;
  const xs = boundPins.map((p) => p.x);
  const zs = boundPins.map((p) => p.z);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minZ = Math.min(...zs);
  const maxZ = Math.max(...zs);
  const side = Math.max(maxX - minX, maxZ - minZ);
  const setHidden = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.value = String(val);
  };
  setHidden("bound-min-x", minX);
  setHidden("bound-max-x", maxX);
  setHidden("bound-min-z", minZ);
  setHidden("bound-max-z", maxZ);
  const aabb = document.getElementById("bound-aabb-readout");
  if (aabb) aabb.textContent = `Square side ${side}: X[${minX}..${maxX}] Z[${minZ}..${maxZ}]`;
}

function updateBoundReadout() {
  const read = document.getElementById("bound-pin-readout");
  if (!read) return;
  if (boundDrawMode && boundAnchor) {
    read.textContent = "Drawing · pick opposite corner";
  } else if (boundClosed && boundPins.length >= 4) {
    const side = Math.max(
      Math.abs(boundPins[1].x - boundPins[0].x),
      Math.abs(boundPins[3].z - boundPins[0].z),
    );
    read.textContent = `Square side ${side}${boundDrawMode ? " · drawing" : ""}`;
  } else {
    read.textContent = boundDrawMode ? "Drawing · click first corner" : "No square";
  }
  syncBoundFieldsFromPins();
}

function updateCornerPinMarkers() {
  const host = document.getElementById("corner-pins");
  if (!host || !viewport) return;
  host.innerHTML = "";
  const scaleX = viewport.clientWidth / canvas.width;
  const scaleY = viewport.clientHeight / canvas.height;
  const markers = boundClosed ? boundPins : boundAnchor ? [boundAnchor] : [];
  markers.forEach((p, i) => {
    const [sx, sy] = worldToScreen(p.x, p.z);
    const el = document.createElement("div");
    el.className = "corner-pin-marker";
    el.textContent = String(i + 1);
    el.style.left = `${sx * scaleX}px`;
    el.style.top = `${sy * scaleY}px`;
    host.appendChild(el);
  });
}

function setBoundDrawMode(on) {
  boundDrawMode = !!on;
  if (on) {
    boundClosed = false;
    boundPins = [];
    boundAnchor = null;
    pinMode = false;
    boundCursor = null;
    setFollow(false);
  } else {
    boundCursor = null;
    if (!boundClosed) boundAnchor = null;
  }
  const btn = document.getElementById("btn-bound-draw");
  if (btn) btn.classList.toggle("is-active", boundDrawMode);
  if (viewport) viewport.classList.toggle("is-pinning", boundDrawMode || pinMode);
  clampCamera();
  updateBoundReadout();
  updateCornerPinMarkers();
  needsDraw = true;
}

function readBoundariesFromForm() {
  if (boundPins.length >= 4) syncBoundFieldsFromPins();
  const corners = boundPins.map((p) => ({ x: p.x, z: p.z }));
  return {
    enabled: !!document.getElementById("bound-enabled")?.checked,
    place_barriers: true,
    wall_y_min: Number(document.getElementById("bound-wall-y")?.value ?? 60),
    wall_height: Number(document.getElementById("bound-wall-h")?.value ?? 16),
    min_x: Number(document.getElementById("bound-min-x")?.value ?? -64),
    max_x: Number(document.getElementById("bound-max-x")?.value ?? 64),
    min_z: Number(document.getElementById("bound-min-z")?.value ?? -64),
    max_z: Number(document.getElementById("bound-max-z")?.value ?? 64),
    enforce: document.getElementById("bound-enforce")?.value || "soft",
    corners,
    vertices: corners,
  };
}

async function saveWorldSettings(partialStatusId) {
  const base = worldSettingsCache || { rules: {}, boundaries: {}, world: {} };
  const payload = {
    rules: { ...base.rules, ...readRulesFromForm() },
    boundaries: { ...base.boundaries, ...readBoundariesFromForm() },
    world: base.world || {},
  };
  const res = await fetch("/api/world/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(apiErrorMessage(body, res.statusText));
  fillWorldForms(body.settings || payload);
  const msg = body.apply_error
    ? `Saved (RCON: ${body.apply_error})`
    : "Saved and applied";
  setStatus(partialStatusId, msg, !!body.apply_error);
  return body;
}

document.getElementById("btn-save-rules")?.addEventListener("click", async () => {
  setStatus("world-rules-status", "Applying…", false);
  try {
    await saveWorldSettings("world-rules-status");
  } catch (err) {
    setStatus("world-rules-status", String(err.message || err), true);
  }
});

document.getElementById("btn-save-boundaries")?.addEventListener("click", async () => {
  if (boundPins.length < 4 || !boundClosed) {
    setStatus(
      "boundaries-status",
      "Draw a square on the map first (two clicks)",
      true,
    );
    return;
  }
  setStatus("boundaries-status", "Setting worldborder…", false);
  try {
    const body = await saveWorldSettings("boundaries-status");
    const n = body.barrier_commands || 0;
    setStatus(
      "boundaries-status",
      body.apply_error
        ? `Saved (${body.apply_error})`
        : `Worldborder applied (${n} cmds)`,
      !!body.apply_error,
    );
  } catch (err) {
    setStatus("boundaries-status", String(err.message || err), true);
  }
});

document.getElementById("btn-preload-map")?.addEventListener("click", () => {
  if (mapPreloadBusy) {
    setStatus("boundaries-status", "Preload already running…", false);
    return;
  }
  if (boundPins.length < 4 || !boundClosed) {
    setStatus(
      "boundaries-status",
      "Draw a square on the map first (two clicks)",
      true,
    );
    return;
  }
  const xs = boundPins.map((p) => p.x);
  const zs = boundPins.map((p) => p.z);
  const min_x = Math.min(...xs);
  const max_x = Math.max(...xs);
  const min_z = Math.min(...zs);
  const max_z = Math.max(...zs);
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    setStatus("boundaries-status", "Not connected to viewer", true);
    return;
  }
  mapPreloadBusy = true;
  const sideBlocks = Math.max(max_x - min_x, max_z - min_z);
  const estTiles = Math.ceil(sideBlocks / tileSize) ** 2;
  setStatus(
    "boundaries-status",
    `Preloading map… (~${estTiles} tiles, up to 8 scout bots)`,
    false,
  );
  send({ type: "map_preload", min_x, max_x, min_z, max_z, max_tiles: 512, workers: 8 });
});

document.getElementById("btn-bound-draw")?.addEventListener("click", () => {
  setBoundDrawMode(!boundDrawMode);
  if (boundDrawMode) {
    setStatus("boundaries-status", "Click first corner (fixed), then drag to size the square", false);
  }
});

document.getElementById("btn-bound-clear")?.addEventListener("click", () => {
  boundPins = [];
  boundClosed = false;
  boundAnchor = null;
  setBoundDrawMode(false);
  updateBoundReadout();
  updateCornerPinMarkers();
  const aabb = document.getElementById("bound-aabb-readout");
  if (aabb) aabb.textContent = "Square: —";
  needsDraw = true;
});

document.getElementById("btn-import-world")?.addEventListener("click", async () => {
  const input = document.getElementById("world-zip");
  if (!input?.files?.length) {
    setStatus("world-import-status", "Choose a .zip first", true);
    return;
  }
  const fd = new FormData();
  fd.append("file", input.files[0]);
  setStatus("world-import-status", "Uploading…", false);
  try {
    const res = await fetch("/api/world/import", { method: "POST", body: fd });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(apiErrorMessage(body, res.statusText));
    if (body.settings) fillWorldForms(body.settings);
    setStatus(
      "world-import-status",
      body.hint || "Imported — restart Minecraft to load",
      false,
    );
  } catch (err) {
    setStatus("world-import-status", String(err.message || err), true);
  }
});

document.getElementById("btn-restart-mc")?.addEventListener("click", async () => {
  setStatus("world-import-status", "Restarting Minecraft…", false);
  try {
    const res = await fetch("/api/world/restart", { method: "POST" });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(apiErrorMessage(body, res.statusText));
    setStatus("world-import-status", body.message || "Restarted", false);
  } catch (err) {
    setStatus("world-import-status", String(err.message || err), true);
  }
});

loadWorldSettings();
loadWorkshopSettings();

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
  } else if (e.key === "Escape" && (pinMode || boundDrawMode)) {
    setPinMode(false);
    setBoundDrawMode(false);
    updateBoundReadout();
  }
});

setFollow(true);
connect();
requestAnimationFrame(draw);
