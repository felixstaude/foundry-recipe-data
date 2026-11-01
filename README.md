# Foundry Recipe Data

This repository provides **public, versioned crafting data** for the game **Foundry** (by Channel 3 Entertainment).

The data is automatically extracted from the official **Foundry Modkit / Asset packs**, processed into clean JSON files, and published via **GitHub Pages** so that tools, websites, and calculators can consume it using **simple HTTP GET requests**.

---

## 📦 What’s included

Each version contains the following files:

- `recipes_clean.json`  
  Cleaned crafting recipes with inputs, outputs, crafting time, tags, and calculated rates.
- `machines.json`  
  Automatically derived machine tiers and crafting speed multipliers.
- `tags.json`  
  All crafting tags with identifiers and display names.
- `speeds_by_tag.json`  
  Crafting speed multipliers extracted from recipe info boxes.
- `speeds_by_tag_report.txt`  
  Human-readable debug report of extracted speed data.
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

The data is extracted using a custom Python pipeline that:

1. Parses Foundry Unity `.asset` files
2. Extracts crafting recipes, tags, and speed markers
3. Normalizes and validates the data
4. Publishes a versioned, static dataset

The build process itself is **not automated via GitHub Actions** and is intentionally run manually to match official Foundry releases.

---

## 📜 Disclaimer

This project is **not affiliated with or endorsed by Channel 3 Entertainment**.  
Foundry and all related assets are property of their respective owners.

This repository only contains **derived, non-binary data** intended for community tools and analysis.

---

## ❤️ Credits

Created and maintained by **Felix Staude**  
Built for use with the **Foundry Calculator** and other community projects.

Contributions, suggestions, and feedback are welcome!
