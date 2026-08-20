# D356-0316 Human-Review Packet

Read-only investigation of `D356-0316` only. Nothing was modified: no parser change, no catalog write, no linkage, no review-state change.

## Experiment

- Experiment ID: `D356-0316`
- Device: D356 (directory context `D356 WSe2_AuSplitGate`)
- State: `needs_review=true`, `parser_version=device_directory_context/v2`
- Processed files:
  - `Processed Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG4V-SweepBG1=2_Vb+2to-8_avg1_DR_R_Self.dat` (15:30:13)
  - `Processed Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG4V-SweepBG1=2_Vb+2to-8_avg1_DR_R_Self.png` (15:30:13, valid PNG, 111,885 bytes)

Reduced measurement stem (after `_avg1_DR_R_Self` suffix strip):

`YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG4V-SweepBG1=2_Vb+2to-8`

## Parsed metadata (persisted)

- measurement_type: absorption (REF)
- measurement_point_label: pa (measurement point/location)
- temperature_K: 3.6
- magnetic_field_T: null
- excitation_wavelength_nm: null (center_wavelength_nm: 720.0, `720nmc`)
- integration_time_s: 0.06, averages: 10 (`0p06sx10`)
- bias_start_V: 2.0, bias_stop_V: -8.0 (`Vb+2to-8`)
- fixed_top_gate_V: 4.0 (normalized from `FixTG4V`)
- active_gate_configuration: null; fixed_gate_values: {}
- electrical_connections: BG2-CG (electrically tied, bias source)
- gate_constraints: [] (`SweepBG1=2` is unparseable on both raw and processed stems; not a discriminator)
- counter suffix: none

## Raw-file candidates (same device, same `Initial Data` folder)

All raw files sharing point `pa`, 3.6 K, REF, `720nmc`, `0p06sx10`:

| Raw filename | mtime | Vtg_set/Vtg_meas (in-file) | Vbias_start (in-file) | notes |
| --- | --- | --- | --- | --- |
| `..._FixTG-SweepBG1=2_Vb+2to-8.csv` | 15:25:08 | 4 / 4 | 2 | filename omits gate value |
| `..._FixTG=-3-SweepBG1=2_Vb+8to0.csv` | 15:59:29 | -3 / -3 | 8 | different bias range |
| `..._FixTG=-4-SweepBG1=2_Vb+8to-2.csv` | 15:37:24 | -4 / -4 | 8 | different bias range |
| `..._FixTG=-4-SweepBG1=2_Vb+8to0.csv` | 15:50:25 | -4 / -4 | 8 | different bias range |
| `..._FixTG=-6-SweepBG1=2_Vb0to+12.csv` | 16:15:42 | -6 / -6 | 0 | different bias range |
| `..._BG1+BG2=0_Vb+8to-8.csv` | 16:59:52 | - | 8 | different sweep/constraint |
| `..._BG1-BG2=0_Vb-8to+8.csv` | 17:06:17 | - | -8 | different sweep/constraint |

## Key evidence: the raw file's own data records +4 V

The file `YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG-SweepBG1=2_Vb+2to-8.csv` has header columns `Vbg_set,Vbg_meas,Vtg_set,Vtg_meas,Vbias_set,Vbias_meas,...`. Its first data row reads:

`Vbg_set=2  Vbg_meas=2  Vtg_set=4  Vtg_meas=4  Vbias_set=2  Vbias_meas=2`

The filename convention is verified on sibling raws: `FixTG=-3` -> `Vtg=-3`, `FixTG=-4` -> `Vtg=-4`, `FixTG=-6` -> `Vtg=-6`. The `FixTG` (no value) raw therefore corresponds to a measurement actually recorded with the top gate at **+4 V**, matching the processed `FixTG4V` naming. The filename simply omitted the value; the file's own data did not.

## Chronological/name-neighbor context

- Raw `FixTG` file: 15:25:08. Processed `FixTG4V` pair: 15:30:13 (~5 min later, same session).
- Sibling cadence matches: raw `FixTG=-4` 15:37:24 -> `_Self` 15:40:06, `_External` 15:43:16; raw `-3` 15:59:29 -> processed 16:02:14; raw `-6` 16:15:42 -> processed 16:50:32.
- Zero processed files carry the exact raw spelling `FixTG-SweepBG1=2_Vb+2to-8` (count 0), so the raw has no same-named processed counterpart.
- `FixTG4V` appears only in these two processed files; no raw anywhere uses `FixTG4V` or `FixTG=4` in this point/ref family.

## Field compatibility vs the unique candidate raw

| field | processed (D356-0316) | raw `FixTG...Vb+2to-8.csv` | compatible |
| --- | --- | --- | --- |
| sample_id | D356 | D356 | yes |
| measurement_type | absorption | absorption | yes |
| point | pa | pa | yes |
| temperature | 3.6 | 3.6 | yes |
| center wavelength | 720.0 | 720.0 | yes |
| integration/averages | 0.06 / 10 | 0.06 / 10 | yes |
| bias range | +2 to -8 | +2 to -8 | yes |
| gate (filename) | 4.0 | none (omitted) | filename mismatch only |
| gate (in-file data) | 4.0 (from name) | +4 V (Vtg_set/meas) | yes |
| connections | BG2-CG | BG2-CG | yes |
| counter suffix | none | none | yes |

The only difference between the processed reduced stem and this raw filename is the token `FixTG4V` vs `FixTG` (the raw omitted `4V`). All other deterministic fields, including the counter identity and the sweep configuration, match, and the raw's internal data confirms +4 V.

## Conclusion for the human reviewer

Evidence strongly indicates `FixTG4V` corresponds to the existing raw measurement `Initial Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG-SweepBG1=2_Vb+2to-8.csv` whose filename omitted the `4V`: the raw file's own recorded `Vtg_set/Vtg_meas` is +4 V, the measurement context is otherwise identical, and the chronological cadence matches every sibling raw->processed pair. This is explicit in-file evidence, not a generic typo rule and not fuzzy matching.

## Decision options (pick exactly one)

- `MATCH TO RAW Initial Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG-SweepBG1=2_Vb+2to-8.csv`
- `LEGITIMATE PROCESSED-ONLY MEASUREMENT`
- `UNKNOWN`

No relationship was persisted during this read-only review; D356-0316 remains `needs_review=true` and unchanged.
