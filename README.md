# FOUNDRY game data

Versioned JSON data for the game [FOUNDRY](https://store.steampowered.com/app/983870/) (Steam app 983870), extracted from
the installed game files. One folder per game version, intended as a data source for wikis and production calculators.

Current data is in `out/`. The files in the repository root (`index.json`, `latest.json`, `v0.6.0.22650/`, `v0.6.0.24200/`)
belong to the legacy data set, see [Legacy data](#legacy-data-no-longer-updated-machine-speeds-are-incorrect) at the end of
this file.

Covered: items, fluids and gases, crafting tags, recipes with craft time and per-minute rates for every machine that can run
them (full power, no workstation bonus; including hand crafting), machines and buildings, research and exploration unlocks, the
assembly line (robot production) and the game's translations.

## Contents of `out/`

```
out/
  index.json                  all exported versions
  latest.json                 points to the newest version
  v<gameVersion>/             e.g. v0.6.0.26518
    manifest.json
    items.json
    elements.json
    crafting_tags.json
    recipes.json
    machines.json
    research.json
    assembly_line.json
    template_fields.json
    localization/<lang>.json
    schemas/*.schema.json
    CHANGES.md
```

| File | Content |
|---|---|
| `index.json` | `{"latest", "versions": [{"version", "gameVersion", "steamBuildId", "title", "description", "generatedAt"}]}` |
| `latest.json` | `{"version", "gameVersion", "steamBuildId", "title", "description", "generatedAt"}`; `version` is the folder name |
| `manifest.json` | game version, Steam build, title and description, Unity version, template source, warnings, and `files`: entry count and sha256 for every data and localization file |
| `items.json` → `items[]`, `categories[]`, `creativeModeCategories[]` | items: stack size, flags, category, fuel value, market and sales data, recipes that use or produce them; the item categories and creative-mode categories |
| `elements.json` → `elements[]` | fluids and gases |
| `crafting_tags.json` → `tags[]` | crafting tags and the machines that accept them |
| `recipes.json` → `recipes[]` | inputs, outputs and base time; `derived.producers[]` gives craft time and per-minute rates for each machine that can run the recipe (hand crafting appears as the pseudo-machine `character`) |
| `machines.json` → `machines[]` | all buildable objects: name, placing item, size, power, crafting speed and accepted tags, fixed recipe or recipe list, fluid boxes, item slots |
| `research.json` → `research[]`, `explorationUnlocks[]` | research costs, dependencies, unlocks and duration; exploration unlocks |
| `assembly_line.json` → `constants`, `machines[]`, `objects[]` | assembly line blocks and robots: parts, paint variants, stages and actions, total inputs, energy, throughput |
| `localization/<lang>.json` | translated names and descriptions under `strings.<category>.<identifier>` (categories such as `items`, `machines`, `recipes`, `research`); 19 languages, listed in `manifest.languages` |
| `template_fields.json` | all field paths of all template types in this game version |
| `schemas/*.schema.json` | the JSON Schemas (Draft 2020-12) every file was validated against |
| `CHANGES.md` | changes compared with the previously exported version (German) |

Conventions:

- Every data file starts with a header `{"schema": "foundry-data/<file>@1", "gameVersion": …}`.
- Top-level lists are sorted by `identifier`. In `assembly_line.json`, `parts`, `colorVariants` and `stages[].actions` keep the
  game's order (actions in depth-first order of the action tree).
- Identifiers are the game's own identifiers (e.g. `_base_assembler_i`). Files reference each other only by identifier, except
  the pseudo-machine `character` (hand crafting) in `recipes.json` and `crafting_tags.json`, which has no entry in `machines.json`.
- Units are part of the field name, e.g. `timeMs`, `craftTimeSec`, `powerKJ`, `consumptionKW`, `capacityLiters`, `weightGrams`,
  `perMinute`.
- Texts in the data files are the English originals; translations are in `localization/<lang>.json`.
- Values computed by the exporter are mostly under a key `derived`. Some resolved fields sit outside it, e.g.
  `machines[].name`, `item`, `modeName`, `itemAlternatives` and `assembly_line.json` → `objects[].researchedBy`;
  `findings/schema.md` names the source of every field.
- `title` and `description` name the game version as shown in the game menu (e.g. `"Update 4"`, `"Rails & Reactors"` for
  0.6.0.26518). They are not part of the game files and are entered by hand; `null` if unknown.
- A version folder is named `v<gameVersion>`; if that folder already exists with a different Steam build, the new one is
  named `v<gameVersion>-b<steamBuildId>`. Older version folders stay available.

The authoritative format description is [`findings/schema.md`](findings/schema.md) (German).

## Fetching the data

Read `latest.json` to get the current version folder, then that folder's `manifest.json`, then the files you need.

```sh
BASE=https://raw.githubusercontent.com/felixstaude/foundry-recipe-data/main/out

VERSION=$(curl -fsSL "$BASE/latest.json" | jq -r .version)              # e.g. v0.6.0.26518
curl -fsSL "$BASE/$VERSION/manifest.json" -o manifest.json
jq '{gameVersion, steamBuildId, title, description, files: (.files | keys)}' manifest.json

curl -fsSL "$BASE/$VERSION/recipes.json" -o recipes.json
echo "$(jq -r '.files["recipes.json"].sha256' manifest.json)  recipes.json" | sha256sum -c
```

```js
const BASE = 'https://raw.githubusercontent.com/felixstaude/foundry-recipe-data/main/out';
const get = async (path) => {
  const res = await fetch(`${BASE}/${path}`);
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
};

const { version } = await get('latest.json');
const manifest = await get(`${version}/manifest.json`);
console.log(manifest.gameVersion, manifest.title, manifest.files['recipes.json'].count);
const { recipes } = await get(`${version}/recipes.json`);
const names = (await get(`${version}/localization/de.json`)).strings.items;   // { "<item id>": { name, description? } }
```

To stay on one game version, use its folder (e.g. `v0.6.0.26518/`) instead of reading `latest.json`.

## Values not confirmed in game (†)

Some exported values have not been confirmed in game yet. Most follow from the game code but have not been measured; two
(entries 12 and 13) are assumptions that the game files cannot settle. They are marked with † below.
[`findings/open_questions.md`](findings/open_questions.md) (German) lists each entry with its current status, the assumption used
by the export and a measurement procedure; that file is authoritative. The JSON files themselves carry no marker.

| Value | Where | Basis | Entry in `open_questions.md` |
|---|---|---|---|
| † hand-crafting times and rates (`timeMs / 3`, rounded down to whole game ticks, 60 per second) | `recipes.json` → `recipes[].derived.producers[]` with `machine: "character"` | game code, not measured | 1 |
| † Heavy Caster speed ×32 | `_base_casting_building_base` in `machines.json` → `machines[].crafting.speedMultiplier` and in `recipes.json` → `recipes[].derived.producers[]` | game code, not measured | 3 |
| † assembly line throughput | `assembly_line.json` → `objects[].derived.singleStartObjectsPerMinute`, `objects[].derived.maxObjectsPerMinute` | game code, not measured | 4 |
| † painter energy (painting is mandatory, all parts count) | `assembly_line.json` → `objects[].derived.painterPowerKJ`, `objects[].derived.totalPowerKJ`, `objects[].derived.fullPaint[].powerKJ` | game code, not measured | 5 |
| † research duration | `research.json` → `research[].derived.timeSecOneServer` | game code, not measured | 9 |
| † names of buildings that two items can place (natural trees and plants, `_base_decor_support_straight`) | `machines.json` → `machines[].name`, `item`, `modeName`, `itemAlternatives`; `localization/<lang>.json` → `strings.machines.<id>.name`, `modeName` | assumption | 12 |
| † no fuel value for items without the `BURNABLE` flag | `items.json` → `items[].fuel` (`null`) | assumption | 13 |
| † Drop Pods (base station) speed 1 and craft times, rounded down to whole game ticks | `_base_baseStation01` in `machines.json` → `machines[].crafting.speedMultiplier` and in `recipes.json` → `recipes[].derived.producers[]` | game code, not measured | 14 |

## Running the extractor

Requirements: Python 3.10 or newer, PyYAML, and an installed copy of FOUNDRY (the Windows build; under Linux via Steam Proton).

```sh
pip install pyyaml
python3 extractor/export check                       # compare the installed version with out/latest.json
python3 extractor/export out                         # export the installed version to out/v<gameVersion>/
python3 extractor/export verify out/v0.6.0.26518     # check all files against the sha256 values in manifest.json
python3 extractor/export itemsheet "Assembler I"     # data sheet for one item, building or robot as Markdown (German);
                                                     # --json prints JSON, --out DIR writes both
FOUNDRY_REQUIRE_GAME=1 python3 -m unittest discover -s extractor/tests   # run the tests (fail if the game is not found)
```

Exporting the Steam build of the newest version folder again replaces that folder (identical data, only `generatedAt` changes),
so run `check` first. The game folder is found through the Steam libraries; to set it explicitly, pass it as the first argument
(`python3 extractor/export "<game folder>" out`) or set `FOUNDRY_GAME_DIR`. Options, exit codes and warnings are described in
[`extractor/README.md`](extractor/README.md), the procedure for a new game version in [`UPDATE.md`](UPDATE.md) (both German).

## License

The extractor code and documentation in this repository are licensed under the [MIT License](LICENSE). The MIT License does not
apply to the game content in this repository (names, descriptions, translations and values from FOUNDRY); the game and its
content belong to their respective owners.

## Disclaimer

This is an unofficial fan project. It is not affiliated with, endorsed by or connected to Channel 3 Entertainment or Paradox
Interactive. Apart from the extractor code and its documentation, the repository contains only data extracted and derived from
the game files (JSON, Markdown and plain text), including the game's names, descriptions and translations. It contains no game
files, game code or game assets such as textures, icons, models or audio; icons are referenced by identifier only.

## Legacy data (no longer updated; machine speeds are incorrect)

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
