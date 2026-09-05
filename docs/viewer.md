# Use the live viewer

After `.\run.ps1` or `./run.sh`, open [http://127.0.0.1:8000](http://127.0.0.1:8000).

The layout is three columns:

- **Left — Configure** — add agents, watcher roles, player list  
- **Center — Map** — top-down world (drag to pan, scroll to zoom)  
- **Right — Chat & events** — log + message box  

You can hide either sidebar with **×**, or toggle **Config** / **Chat** in the top bar.

---

## How to spawn an agent

1. Open **Add agent** on the left.
2. Fill in:
   - **Username** — in-game name (max 16 chars)
   - **Goal** — what the LLM should chase
   - **System prompt / persona** — personality and style
   - Optional extra instructions
3. Optional spawn location:
   - Click **Pin on map**, then click the map
   - Set **Y** (default 64)
4. Click **Spawn agent**.

Agents always join as normal survival bots. They are **not** OP or spectators.

---

## How to watch in Minecraft (human account)

Use **Watcher roles** for *your* Minecraft username (not agent bots):

1. Join the same server with that exact username.
2. Open **Watcher roles**, enter the name, pick a role, **Assign role**.

| Role | Effect |
|---|---|
| Spectator | OP + spectator (free camera) |
| OP | Operator |
| Survival / Creative / Adventure | Set gamemode |
| Remove OP | `deop` |

This uses RCON on the bundled Docker server (`ENABLE_RCON=true`, password `simulatecraft`).

---

## How to control the simulation

Top bar:

| Control | What it does |
|---|---|
| Play / Pause | Run or freeze the tick loop |
| Step / ×10 | Advance 1 or 10 ticks (best while paused) |
| − / + and speed menu | Change tick rate |
| +1k | Add 1000 to max tick budget |
| Follow | Keep the map centered on agents |

Keyboard: `Space` pause, `.` step, `Shift+.` ×10, `+`/`−` speed, `F` follow.

Status chips show `t=current / max` and ticks per second.

---

## How to chat with agents

1. In the right panel, pick a target (**Everyone** or one agent).
2. Type a message and **Send**.

Agents see pending messages in their next decide step and should reply in chat
when the model follows persona instructions.

---

## Tips

- Collapse sidebars for a bigger map.
- Filter the event log with **All / Acts / Chat / Sys**.
- If spawn pin mode is stuck on, press **Esc**.

Next: [How it works](how-it-works.md)
