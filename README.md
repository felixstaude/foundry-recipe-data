# Foundry Recipe Data

This repository provides **public, versioned crafting data** for the game **Foundry** (by Channel 3 Entertainment).

The data is automatically extracted directly from the **Foundry game data**, processed into clean JSON files, and published via **GitHub Pages** so that tools, websites, and calculators can consume it using **simple HTTP GET requests**.

The data comes in two formats:

- **foundry-data v1** under [`/v1/`](#-foundry-data-v1-v1). This is the complete export: items, fluids, recipes with per-machine rates, machines with power and size, research, assembly line, and localization. Use it for new tools.
- **Legacy format** in the root folders (`/v0.6.0.*/`). It contains `recipes_clean.json`, `machines.json` and similar files, and stays unchanged for existing consumers.

---

## 📦 What’s included (legacy format)

Each version contains the following files:

- `recipes_clean.json`  
  Cleaned crafting recipes with inputs, outputs, crafting time, tags, and calculated rates.
- `machines.json`  
  Crafting machines and their crafting speed multipliers. From `v0.6.0.26518` on these are the real buildings taken from the machine templates. Older versions contain estimated tiers (1 / 1.5 / 2).
- `tags.json`  
  All crafting tags with identifiers and display names.
- `speeds_by_tag.json`  
  Crafting speed multipliers per crafting tag, taken from the machines that use it.
- `speeds_by_tag_report.txt`  
  Human-readable debug report of extracted speed data.
- `assembly_line.json`  
  Assembly line robots with parts, actions, energy, and throughput.
- `build_meta.json`  
  Technical build metadata (no personal or local system data).
- `manifest.json`  
  Version manifest with title, description, timestamp, and file list.

---

## 🌐 Public API (GitHub Pages)

All data is served statically via GitHub Pages.

### Base URL
```
https://felixstaude.github.io/foundry-recipe-data/
```

### Endpoints

#### 🔹 List all available versions
```
GET /index.json
```

#### 🔹 Get latest version
```
GET /latest.json
```

#### 🔹 Get version manifest
```
GET /vX.Y.Z/manifest.json
```

#### 🔹 Get specific data file
```
GET /vX.Y.Z/recipes_clean.json
GET /vX.Y.Z/machines.json
GET /vX.Y.Z/tags.json
GET /vX.Y.Z/speeds_by_tag.json
```

Example:
```
https://felixstaude.github.io/foundry-recipe-data/v0.6.0.22650/recipes_clean.json
```

---

## 🧩 foundry-data v1 (`/v1/`)

This is the complete export of a game version, produced by the foundry-data exporter. Every version folder is published byte for byte as exported.

### Endpoints
```
GET /v1/index.json                    all versions: {latest, versions[{version, gameVersion, steamBuildId, channel, title, description, generatedAt}]}
GET /v1/latest.json                   newest version of any channel
GET /v1/latest_stable.json            newest stable version (use this as default)
GET /v1/<version>/manifest.json       schemaVersion, gameVersion, steamBuildId, steamBranch, files{name: {count, sha256}}, ...
GET /v1/<version>/items.json          items (names, categories, flags, stack size, ...)
GET /v1/<version>/elements.json       fluids and gases
GET /v1/<version>/recipes.json        recipes with inputs/outputs, fluids in liters, output chances, per-machine rates
GET /v1/<version>/machines.json       buildings incl. crafting speed, power consumption (kW) and size
GET /v1/<version>/assembly_line.json  assembly-line robots, stations and throughput constants
GET /v1/<version>/research.json       research and exploration unlocks
GET /v1/<version>/crafting_tags.json  crafting tags
GET /v1/<version>/localization/<lang>.json   19 languages
GET /v1/<version>/schemas/*.schema.json      JSON Schemas (Draft 2020-12) of all files
GET /v1/<version>/CHANGES.md          changes against the previous version (German)
```

### Conventions
- Every data file starts with `schema` (e.g. `foundry-data/items@1`), `gameVersion`, `steamBuildId` and `count`. Check `schema` before reading a file.
- `manifest.files` lists the `sha256` and `count` of every file. Clients can verify downloads with it.
- `channel` is `stable` (released build) or `beta` (Steam experimental branch). Treat a missing `channel` as `stable`. Default to `latest_stable.json`, not `latest.json`.
- Folder names are opaque: `v<gameVersion>`, or `v<gameVersion>-b<steamBuildId>` when the same version is re-exported from another build. Read `gameVersion` from the data; do not parse folder names.
- Published version folders are **immutable**. A stable version is never changed in place; new data is published as a new version. The only exception is a beta, which may be replaced by a newer export of the same experimental build.
- Values marked as unverified in the exporter's findings (hand crafting ×3, Heavy Caster ×32, assembly line 31.86/min) come from the game code and have not been measured in game.

---

## 🧠 Recommended Client Flow

1. Fetch the latest version:
   ```
   GET /latest.json
   ```
2. Fetch the version manifest:
   ```
   GET /<version>/manifest.json
   ```
3. Load only the files your tool needs.

This avoids hardcoding file names or versions and keeps clients future-proof.

---

## 🔄 Versioning Strategy

- Each Foundry version is published in its **own folder** (e.g. `v0.6.0.22650`)
- Versions can have a **human-readable title and description**
- Older versions remain available for reproducibility

---

## 🔒 Privacy & Safety

- No personal information
- No local file paths
- No system-specific metadata

All data is safe to mirror, cache, and redistribute.

---

## 🛠 How the data is generated

The data is extracted directly from the Foundry game data. Each build:

1. Reads recipes, machines, crafting tags, and assembly line robots from the game files
2. Calculates rates from the real crafting speed of each machine, including output chances and fluids
3. Normalizes and validates the data
4. Publishes a versioned, static dataset

The build process itself is **not automated via GitHub Actions** and is intentionally run manually to match official Foundry releases. A validation workflow (`scripts/validate.py`) checks every change before it is published: all JSON parses, the hashes and counts match the manifests, the v1 files match their JSON Schemas, the indexes match the folders, and published v1 files are unchanged.

---

## 📜 Disclaimer

This project is **not affiliated with or endorsed by Channel 3 Entertainment**.  
Foundry and all related assets are property of their respective owners.

This repository only contains **derived, non-binary data** intended for community tools and analysis. Game texts, such as item names and the localization files, belong to their owners and are not covered by any license of this repository.

---

## ❤️ Credits

Created and maintained by **Felix Staude**  
Built for use with the **Foundry Calculator** and other community projects.

Contributions, suggestions, and feedback are welcome!
