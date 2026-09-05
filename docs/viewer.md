# Live viewer

The bundled UI at `http://127.0.0.1:8000` is a Minecraft-styled control surface:

- **Map** — full-bleed top-down map (pan / zoom, ±512 from home)
- **Players** — health / food, position, goal
- **Add agent** — spawn bots with persona, system prompt, and optional spawn pin
- **Watcher roles** — assign OP / spectator to *human* Minecraft usernames (observers)
- **Event feed** — filterable acts / chat / system stream
- **Composer** — message one agent or broadcast

## Add an agent from the UI

1. Open **Add agent** in the left Configure panel.
2. Set **username**, **goal**, and **system prompt / persona**.
3. Optional: turn on **Pin on map**, click the map, set **Y**.
4. Click **Spawn agent**.

Agents always play as normal bots (survival). They are never given OP or spectator.

## Watcher roles (humans only)

Join the same Minecraft server with your own account, then use **Watcher roles**:

| Role | Effect |
|---|---|
| Spectator | OP + spectator gamemode (free camera to watch agents) |
| OP | Operator privileges |
| Survival / Creative / Adventure | Set your gamemode |
| Remove OP | `deop` |

Uses the server RCON console (`ENABLE_RCON=true`, password `simulatecraft` on the bundled Docker server).

## Controls

| Input | Action |
|---|---|
| Play / Pause | Resume or pause the runner |
| Step / `·` | Advance one tick (best while paused) |
| ×10 / `Shift+.` | Advance ten ticks |
| − / + | Halve or double tick speed |
| Speed menu | Presets from 0.25× … 8× or Max |
| +1k | Raise max tick budget by 1000 |
| Follow / `F` | Keep camera on agents |
| `Space` | Toggle pause/resume |
| `+` / `−` | Faster / slower |
| Esc | Cancel spawn pin mode |

Status chips show `t=current / max` and live tick rate (`N tps` or `max tps`).

## Protocol

```text
server → client: {"type":"event","event":{...}}
                 {"type":"state","state":{...}}
                 {"type":"map","map":{...}}
                 {"type":"agent_created",...}
client → server: {"type":"chat","text":...,"target":...}
                 {"type":"control","command":"pause"|"resume"|"step"|
                   "faster"|"slower"|"set_tick_rate"|"set_max_ticks"|"extend_ticks"|...,
                   "n"?:int, "value"?:number}
                 {"type":"map","origin_x":...,"origin_z":...,"size":...}
                 {"type":"agent_create","username":...,"persona":...,...}
                 {"type":"agent_delete","agent_id":...}
                 {"type":"watcher_role","username":...,"role":"spectator"|...}
```

REST: `POST /api/agents`, `DELETE /api/agents/{id}`, `POST /api/watchers/role`.

Static assets: `src/simulatecraft/server/static/`.  
API: [`SimulationServer`](reference/server/app.md).
