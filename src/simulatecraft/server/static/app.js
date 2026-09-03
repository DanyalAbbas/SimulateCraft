/* SimulateCraft live viewer — plain JS + canvas, no build step.
   Protocol:
     server → client: {"type":"event","event":{...}} | {"type":"state","state":{...}}
     client → server: {"type":"chat",...} | {"type":"control","command":...}
*/

const canvas = document.getElementById("world");
const ctx = canvas.getContext("2d");
const logEl = document.getElementById("event-log");
const statusEl = document.getElementById("status");
const tickEl = document.getElementById("tick-counter");
const targetSel = document.getElementById("chat-target");
const hudEl = document.getElementById("hud");
const agentCountEl = document.getElementById("agent-count");
const mapOverlay = document.getElementById("map-overlay");

let latestState = null;
let socket = null;
let reconnectDelay = 1000;
let activeFilter = "all";

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${proto}://${location.host}/ws`);
  socket.onopen = () => {
    setStatus("running", "connected");
    reconnectDelay = 1000;
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
  else statusEl.textContent = label;
}

function applyState(state) {
  latestState = state;
  const status = state.status || {};
  const tick = (state.snapshot && state.snapshot.tick) ?? status.tick ?? 0;
  tickEl.textContent = `t=${tick}`;

  if (status.paused) setStatus("paused", "paused");
  else if (status.running) setStatus("running", "running");
  else if (socket && socket.readyState === WebSocket.OPEN) setStatus("running", "connected");

  render();
  updateAgentList(state);
  updateHud(state);
}

function render() {
  if (!latestState) return;
  if (typeof window.customRenderer === "function") {
    window.customRenderer(ctx, latestState);
    return;
  }
  defaultRender(latestState);
}

function defaultRender(state) {
  const snap = state.snapshot || {};
  const world = snap.world || {};
  const agents = snap.agents || {};
  const map = world.map || {};
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const mw = Number(map.width || 128);
  const mh = Number(map.height || 128);
  const originX = Number(map.origin_x != null ? map.origin_x : (world.origin_xz || [0, 0])[0]);
  const originZ = Number(map.origin_z != null ? map.origin_z : (world.origin_xz || [0, 0])[1]);
  const pad = 18;
  const inner = Math.min(canvas.width, canvas.height) - pad * 2;
  const scale = inner / Math.max(mw, mh);
  const offX = (canvas.width - mw * scale) / 2;
  const offY = (canvas.height - mh * scale) / 2;

  ctx.fillStyle = "#d2b48c";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#c4a574";
  ctx.fillRect(offX - 4, offY - 4, mw * scale + 8, mh * scale + 8);

  const hasPixels = Boolean(map.pixels);
  if (mapOverlay) mapOverlay.hidden = hasPixels;

  if (hasPixels) {
    drawMapPixels(map, offX, offY, scale);
  }

  for (const [id, info] of Object.entries(agents)) {
    const p = info.position_3d || info.position;
    if (!p || p.length < 2) continue;
    const wx = Number(p[0]);
    const wz = Number(p.length > 2 ? p[2] : p[1]);
    const x = offX + (wx - originX) * scale;
    const y = offY + (wz - originZ) * scale;
    const yaw = Number(info.yaw || 0);
    drawMapPointer(x, y, yaw, info.name || id);
  }
}

function drawMapPixels(map, offX, offY, scale) {
  const w = map.width;
  const h = map.height;
  const raw = Uint8Array.from(atob(map.pixels), (c) => c.charCodeAt(0));
  const tmp = document.createElement("canvas");
  tmp.width = w;
  tmp.height = h;
  const tctx = tmp.getContext("2d");
  const img = tctx.createImageData(w, h);
  for (let i = 0; i < w * h; i++) {
    img.data[i * 4] = raw[i * 3];
    img.data[i * 4 + 1] = raw[i * 3 + 1];
    img.data[i * 4 + 2] = raw[i * 3 + 2];
    img.data[i * 4 + 3] = 255;
  }
  tctx.putImageData(img, 0, 0);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(tmp, offX, offY, w * scale, h * scale);
}

function drawMapPointer(x, y, yawDeg, name) {
  const rad = ((yawDeg + 180) * Math.PI) / 180;
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(rad);
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
  ctx.font = "600 12px Outfit, system-ui, sans-serif";
  ctx.textAlign = "center";
  const tw = ctx.measureText(name).width;
  ctx.fillStyle = "rgba(40, 28, 16, 0.78)";
  ctx.fillRect(x - tw / 2 - 3, y + 10, tw + 6, 15);
  ctx.fillStyle = "#f5e6c8";
  ctx.fillText(name, x, y + 21);
}

function meter(kind, label, value, max = 20) {
  const pct = Math.max(0, Math.min(100, (Number(value) / max) * 100));
  return `
    <div class="meter ${kind}">
      <span>${label}</span>
      <div class="meter-bar"><div class="meter-fill" style="width:${pct}%"></div></div>
      <span>${Number(value).toFixed(0)}</span>
    </div>`;
}

function updateHud(state) {
  if (!hudEl) return;
  const agents = (state.snapshot || {}).agents || {};
  const entries = Object.entries(agents);
  if (agentCountEl) agentCountEl.textContent = String(entries.length);

  if (!entries.length) {
    hudEl.innerHTML = '<p class="empty">No agents connected yet.</p>';
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
        <article class="agent-row">
          <div>
            <div class="agent-name">${esc(info.name || id)}</div>
            <div class="agent-pos">${esc(pos)}</div>
          </div>
          <div class="agent-stats">${health}${food}</div>
          ${meta ? `<div class="agent-meta">${meta}</div>` : ""}
        </article>`;
    })
    .join("");
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
      addLogEntry(
        `<span class="who">${esc(ev.agent_id)}</span> “${esc(ev.text)}”`,
        ev.tick,
        "chat"
      );
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
  div.innerHTML = `<span class="tick">t${tick >= 0 ? tick : ""}</span>${html}`;
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
  const kinds = (el.dataset.kinds || "").split(/\s+/);
  el.hidden = !kinds.includes(activeFilter);
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

document.getElementById("btn-pause").onclick = () => send({ type: "control", command: "pause" });
document.getElementById("btn-play").onclick = () => send({ type: "control", command: "resume" });
document.getElementById("btn-step").onclick = () => send({ type: "control", command: "step" });

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

window.addEventListener("keydown", (e) => {
  if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT")) {
    return;
  }
  if (e.code === "Space") {
    e.preventDefault();
    const paused = latestState && latestState.status && latestState.status.paused;
    send({ type: "control", command: paused ? "resume" : "pause" });
  } else if (e.key === ".") {
    send({ type: "control", command: "step" });
  }
});

connect();
