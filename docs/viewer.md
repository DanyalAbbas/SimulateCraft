# Live viewer

The bundled UI at `http://127.0.0.1:8000` is a Minecraft-styled control surface:

- **Map** — full-bleed top-down map (pan / zoom, ±512 from home)
- **Players** — health / food, position, goal, OP / gamemode badges
- **Add agent** — spawn bots from the browser with persona, spawn pin, OP, spectator
- **Event feed** — filterable acts / chat / system stream
- **Composer** — message one agent or broadcast

## Add an agent from the UI

1. Open **Add agent** in the right rail.
2. Set **username**, **goal**, and **system prompt / persona**.
3. Optional: turn on **Pin on map**, click the map, set **Y**.
4. Optional: enable **OP**, **Spectator**, or pick a gamemode.
5. Click **Spawn agent**.

OP / teleport / gamemode use the Minecraft server RCON console when available
(`ENABLE_RCON=true`, password `simulatecraft` on the bundled Docker server).

## Controls

| Input | Action |
|---|---|
| Play / Pause | Resume or pause the runner |
| Step | Advance one tick |
| Follow / `F` | Keep camera on agents |
| `Space` | Toggle pause/resume |
| `.` | Step one tick |
| Esc | Cancel spawn pin mode |

## Protocol

```text
server → client: {"type":"event","event":{...}}
                 {"type":"state","state":{...}}
                 {"type":"map","map":{...}}
                 {"type":"agent_created",...}
client → server: {"type":"chat","text":...,"target":...}
                 {"type":"control","command":"pause"|"resume"|"step"|...}
                 {"type":"map","origin_x":...,"origin_z":...,"size":...}
                 {"type":"agent_create","username":...,"persona":...,...}
                 {"type":"agent_delete","agent_id":...}
```

REST: `POST /api/agents`, `DELETE /api/agents/{id}`, `GET /api/agents`.

Static assets: `src/simulatecraft/server/static/`.  
API: [`SimulationServer`](reference/server/app.md).
