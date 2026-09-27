# Changelog

All notable changes to SimulateCraft are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Agent actions for survival loops:
  - `attack` — melee a named entity or the nearest living target
  - `eat` — consume food from inventory (named item or first edible)
  - `collect` — path to the nearest dropped item entity
  - `give` — toss items toward another player
  - `cancel_path` — stop pathfinding / following and clear movement
- World settings: import Java worlds, draw a play-area **square** on the map
  (outside shade + soft/hard enforce) and apply a fast vanilla
  **`worldborder`** (no per-block fill spam), plus day/night / weather /
  mob gamerules (`data/world_settings.json`)
- One-line installers (`install.sh` / `install.ps1`) with OpenRouter-first
  provider messaging
- Docs page: [Worlds, boundaries & rules](docs/worlds.md)
- Configure panel: generate structured system prompts from draft notes
  (`POST /api/agents/generate-prompt`) and bulk-spawn agents from CSV/Excel
  rosters (`POST /api/agents/bulk`)
- Configurable agent workshop (`GET/PUT /api/agents/workshop`): custom
  prompt-generator instructions and roster column maps, with University /
  Minimal presets (stored in `data/agent_workshop.json`)

### Changed

- LLM auto-select prefers OpenRouter over Groq (Groq rate-limits under agent load)
- Installer stops with clear next steps when no LLM key is set (blank `.env`
  values do not count)
- Viewer Configure checkboxes use aligned row layout

### Fixed

- PowerShell installer missing-command message printed `$Name` literally
- Windows `install.ps1` raw.githubusercontent.com 503 documented with jsDelivr fallback
