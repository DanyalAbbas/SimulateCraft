# Live viewer

The bundled UI at `http://127.0.0.1:8000` is a cartography-style control surface:

- **Map** — 128×128 vanilla-colored Minecraft map with player pointers
- **Agents** — health / food meters, position, goal, held item
- **Event feed** — filterable acts / chat / system stream
- **Composer** — message one agent or broadcast

## Controls

| Input | Action |
|---|---|
| Play / Pause | Resume or pause the runner |
| Step | Advance one tick |
| `Space` | Toggle pause/resume |
| `.` | Step one tick |

## Protocol

```text
server → client: {"type":"event","event":{...}}
                 {"type":"state","state":{...}}
client → server: {"type":"chat","text":...,"target":...}
                 {"type":"control","command":"pause"|"resume"|"step"|...}
```

Static assets: `src/simulatecraft/server/static/`.  
API: [`SimulationServer`](reference/server/app.md).
