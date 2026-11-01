# Vergleich mit dem alten Datensatz (v0.6.0.24200 → v0.6.0.26518)

Erzeugt von `extractor/compare_legacy.py`. Achtung: Die Sätze stammen aus **verschiedenen Spielversionen**. Unterschiede bei Rezeptinhalten (Zeit, Zutaten, neue/entfernte Rezepte) können Spiel-Patches sein. Unterschiede bei Geschwindigkeiten, Raten, Fluiden und Maschinen kommen von der **Methode** (alt: aus `_infoBox`-Tooltiptexten geraten; neu: aus den Maschinen-Assets).

## 1. Rezeptmenge

- alt: 300 Rezepte, neu: 350 Rezepte, gemeinsam: 300
- nur neu: 50, nur alt: 0

### Nur im neuen Export

| Tags | Anzahl | Rezepte |
|---|---|---|
| assembler | 14 | `_base_construction_material_ii`, `_base_military_robot_02_arm`, `_base_military_robot_02_head`, `_base_military_robot_02_leg`, `_base_military_robot_02_torso`, `_base_robot_hazard_01_arm`, `_base_robot_hazard_01_head`, `_base_robot_hazard_01_leg`, `_base_robot_hazard_01_torso`, `_base_robot_parts_ii`, `_base_robot_scout_01_arm`, `_base_robot_scout_01_head`, `_base_robot_scout_01_leg`, `_base_robot_scout_01_torso` |
| casting_machine | 1 | `_base_reactive_briquette_i` |
| character, assembler | 20 | `_base_casting_building_base`, `_base_neon_decor_i`, `_base_neon_decor_i_slope`, `_base_neon_decor_i_slope_junctions`, `_base_neon_decor_ii`, `_base_neon_decor_slope`, `_base_neon_decor_slope_junctions`, `_base_npp_cooling_tower_base`, `_base_npp_pressurizer_base`, `_base_npp_reactor_base`, `_base_npp_steam_generator_base`, `_base_npp_steam_turbine_base`, `_base_pipeline_intake_i`, `_base_rail_tracks`, `_base_trainSignal_simple`, `_base_train_engine_01`, `_base_train_loading_station`, `_base_train_station`, `_base_train_wagon_element_01`, `_base_train_wagon_solid_01` |
| chemical_processor | 5 | `_base_fracking_liquid_i`, `_base_ignium_enriched_water`, `_base_liquid_fuel`, `_base_olumic_acid`, `_base_paint` |
| distillation_column | 6 | `_base_basic_refining_gas`, `_base_basic_refining_ldo`, `_base_basic_refining_liquid_polymer`, `_base_hdo`, `_base_impure_hdo`, `_base_xeno_crystal_sludge` |
| electric_arc_furnace | 2 | `_base_liquid_telluxite`, `_base_molten_super_alloy` |
| geothermal_generator | 1 | `_base_geothermal_generator_internal` |
| npp_fuel_mixer | 1 | `_base_npp_press_internal_01` |

16 davon haben Fluid-Ein- oder -Ausgaben. Der alte Datensatz kennt keine Fluide; ob er solche Rezepte bewusst verworfen hat oder ob sie in 0.6.0.24200 fehlten, lässt sich ohne die alten Spieldateien nicht unterscheiden.

## 2. Inhalt gemeinsamer Rezepte

| Feld | Abweichungen |
|---|---|
| Name | 1 |
| timeMs | 0 |
| Item-Eingaben | 0 |
| Item-Ausgaben | 0 |
| Tags | 2 |
| Fluide (fehlen im alten Satz komplett) | 34 |
| Ausgabe mit Wahrscheinlichkeit (alte Rate ignoriert `percentage_str`) | 10 |

### Name

| Rezept | alt | neu |
|---|---|---|
| `_base_pipe_intake_i` | Pipe Intake | Liquid Intake |

### Tags

| Rezept | alt | neu |
|---|---|---|
| `_base_technum_rods_t3` | ['casting_machine'] | ['casting_machine', 'heavy_caster'] |
| `_base_xf_plates_t3` | ['casting_machine'] | ['casting_machine', 'heavy_caster'] |

### Fluide (fehlen im alten Satz komplett)

| Rezept | alt | neu |
|---|---|---|
| `_base_barrel_drain_olumite` | – | out 250 L _base_olumite |
| `_base_barrel_olumite` | – | in 250 L _base_olumite |
| `_base_biomass` | – | in 250 L _base_water |
| `_base_boreal_forest_seed_plants` | – | in 250 L _base_water |
| `_base_boreal_forest_seed_trees` | – | in 250 L _base_water |
| `_base_cement_reprocessed` | – | in 36 L _base_bf_slag |
| `_base_concrete` | – | in 20 L _base_water |
| `_base_cpu` | – | in 80 L _base_olumic_acid |
| `_base_crystal_ii` | – | in 2000 L _base_ignium_enriched_water |
| `_base_dynamite_ii` | – | in 150 L _base_liquid_fuel |
| `_base_energy_cell` | – | in 60 L _base_olumic_acid |
| `_base_explosives_ii` | – | in 50 L _base_ldo |
| `_base_hydraulic_piston` | – | in 30 L _base_ldo |
| `_base_ignium_fuel_rod` | – | in 400 L _base_liquid_fuel |
| `_base_jetpack_fuel` | – | in 30 L _base_liquid_fuel |
| `_base_mic_iii` | – | in 5 L _base_ldo |
| `_base_office_marble_black_deluxe` | – | in 5 L _base_olumite |
| `_base_office_marble_white_deluxe` | – | in 5 L _base_water |
| `_base_polymer_board` | – | in 5 L _base_liquid_polymer |
| `_base_portable_fuel` | – | in 30 L _base_liquid_fuel |
| `_base_rocky_desert_seed_plants` | – | in 250 L _base_water |
| `_base_rocky_desert_seed_trees` | – | in 250 L _base_water |
| `_base_rubber_i` | – | in 5 L _base_liquid_polymer; in 10 L _base_hdo |
| `_base_sandy_desert_seed_plants` | – | in 250 L _base_water |
| `_base_sandy_desert_seed_trees` | – | in 250 L _base_water |
| `_base_space_ship_fuel` | – | in 100 L _base_liquid_fuel; in 20 L _base_water |
| `_base_super_alloy_plate_i` | – | in 50 L _base_molten_super_alloy |
| `_base_technum_rods_t3` | – | in 15 L _base_molten_te |
| `_base_telluxite_wafer` | – | in 400 L _base_liquid_telluxite |
| `_base_tropical_rainforest_seed_plants` | – | in 250 L _base_water |
| `_base_tropical_rainforest_seed_trees` | – | in 250 L _base_water |
| `_base_tundra_seed_plants` | – | in 250 L _base_water |
| `_base_tundra_seed_trees` | – | in 250 L _base_water |
| `_base_xf_plates_t3` | – | in 15 L _base_molten_xf |

### Ausgabe mit Wahrscheinlichkeit (alte Rate ignoriert `percentage_str`)

| Rezept | alt | neu |
|---|---|---|
| `_base_boreal_forest_seed_plants` | 0.6000000000000001 /min (ohne Chance) | 0.3 /min (Chance 0.5) |
| `_base_boreal_forest_seed_trees` | 0.6000000000000001 /min (ohne Chance) | 0.3 /min (Chance 0.5) |
| `_base_rocky_desert_seed_plants` | 0.6000000000000001 /min (ohne Chance) | 0.3 /min (Chance 0.5) |
| `_base_rocky_desert_seed_trees` | 0.6000000000000001 /min (ohne Chance) | 0.3 /min (Chance 0.5) |
| `_base_sandy_desert_seed_plants` | 0.6000000000000001 /min (ohne Chance) | 0.3 /min (Chance 0.5) |
| `_base_sandy_desert_seed_trees` | 0.6000000000000001 /min (ohne Chance) | 0.3 /min (Chance 0.5) |
| `_base_tropical_rainforest_seed_plants` | 0.6000000000000001 /min (ohne Chance) | 0.3 /min (Chance 0.5) |
| `_base_tropical_rainforest_seed_trees` | 0.6000000000000001 /min (ohne Chance) | 0.3 /min (Chance 0.5) |
| `_base_tundra_seed_plants` | 0.6000000000000001 /min (ohne Chance) | 0.3 /min (Chance 0.5) |
| `_base_tundra_seed_trees` | 0.6000000000000001 /min (ohne Chance) | 0.3 /min (Chance 0.5) |

## 3. Crafting-Tags

- alt: 15, neu: 17 (CraftingTag-Templates)
- nur neu: `heavy_caster`, `npp_fuel_mixer`
- nur alt: –
- in Rezepten benutzt, aber ohne CraftingTag-Template: `base_station`

## 4. Maschinen und Geschwindigkeiten

Alt: pro Tag immer die Stufen 1 / 1,5 / 2, geraten aus den `===[SPEED x]===`-Markern im `_infoBox`. Diese Marker stehen in **jedem** Rezept-Tooltip, egal welche Maschinen es gibt. Neu: Maschinen aus `BuildableObjectTemplate`, Multiplikator aus `*_recipeTimeModifier_str`, Zuordnung wie `CraftingRecipe.onLoadPostprocess`.

| Tag | alt: Stufen | neu: echte Maschinen (Multiplikator) | erfundene Stufen (nur alt) | fehlende Stufen (nur neu) |
|---|---|---|---|---|
| `advanced_smelter` | 1.0, 1.5, 2.0 | `_base_smelter_i` ×1.5 (AutoProducer) | 1.0, 2.0 | – |
| `assembler` | 1.0, 1.5, 2.0 | `_base_assembler_i` ×1 (Producer), `_base_assembler_ii` ×1.5 (Producer), `_base_assembler_iii` ×2 (Producer) | – | – |
| `assembler_fluid` | 1.0, 1.5, 2.0 | `_base_assembler_fluid_i` ×1 (Producer) | 1.5, 2.0 | – |
| `barrel_filler` | 1.0, 1.5, 2.0 | `_base_barrel_filler_i` ×1 (Producer) | 1.5, 2.0 | – |
| `base_station` | 1.0, 1.5, 2.0 | `_base_baseStation01` ×1 (BaseStation (fix/Liste)) | 1.5, 2.0 | – |
| `casting_machine` | 1.0, 1.5, 2.0 | `_base_casting_machine` ×1 (Producer) | 1.5, 2.0 | – |
| `character` | 1.0, 1.5, 2.0 | `character` ×3 (Character (Simulation timeMs/3, Tooltip /5)) | 1.0, 1.5, 2.0 | 3 |
| `chemical_processor` | 1.0, 1.5, 2.0 | `_base_chemical_processor_i` ×1 (Producer) | 1.5, 2.0 | – |
| `crusher` | 1.0, 1.5, 2.0 | `_base_crusher_i` ×1 (Producer), `_base_crusher_ii` ×2 (Producer) | 1.5 | – |
| `crystal_refiner` | 1.0, 1.5, 2.0 | `_base_crystal_refiner_i` ×1 (Producer) | 1.5, 2.0 | – |
| `distillation_column` | 1.0, 1.5, 2.0 | `_base_distillation_column_i` ×1 (Producer) | 1.5, 2.0 | – |
| `electric_arc_furnace` | 1.0, 1.5, 2.0 | `_base_electric_arc_furnace` ×1 (Producer) | 1.5, 2.0 | – |
| `geothermal_generator` | 1.0, 1.5, 2.0 | `_base_geothermal_generator_i` ×1 (Producer (fix/Liste)) | 1.5, 2.0 | – |
| `greenhouse` | 1.0, 1.5, 2.0 | `_base_greenhouse_i` ×1 (Producer) | 1.5, 2.0 | – |
| `heavy_caster` | – | `_base_casting_building_base` ×32 (ModularEntityProducer) | – | 32 |
| `npp_fuel_mixer` | – | `_base_npp_pressurizer_base` ×1 (ModularEntityProducer (fix/Liste)) | – | 1 |
| `smelter` | 1.0, 1.5, 2.0 | `_base_smelter_small_i` ×1 (AutoProducer) | 1.5, 2.0 | – |
| `smelter_lava` | 1.0, 1.5, 2.0 | `_base_smelter_lava_i` ×1 (AutoProducer), `_base_smelter_lava_ii` ×2 (AutoProducer) | 1.5 | – |

Zusätzlich neu pro Maschine: Strom (`energyConsumptionKW_str`), Größe, Fluid-Boxen, Item-Slots, Name und Item.

## 5. Was der alte Datensatz gar nicht hat

- Assembly Line: 9 Roboter mit Stufen/Aktionen, Starter-/Verkaufs-Items, Lackverbrauch, Durchsatz (14 AL-Maschinen).
- Fluid-Ein-/Ausgaben von Rezepten, Wahrscheinlichkeiten von Ausgaben.
- Items, Elemente, Forschung (inkl. Erkundungs-Freischaltungen) und Freischaltung pro Rezept.
- Lokalisierung in allen Spielsprachen.
- Handwerk: Charakter-Zeit = `timeMs / 3` in ganzen 60-Hz-Ticks (nativ `FoundryNative.dll` `CraftingAction::reinitialize`, `findings/verification.md`; der Tooltip `Character.getCraftingTimeForRecipeInMs` zeigt `/5`, nur UI). Alt: Faktor 1.
