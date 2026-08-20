# D356 Unresolved Human-Review Packet

Read-only review packet for the two D356 experiments the deterministic
device-directory rule flags as processed-only (`needs_review=1`,
`parser_version='device_directory_context/v1'`). This packet is for human
inspection only: nothing was persisted, and no relationship or derivation
was written. Catalog, experiments, and derivation rule are unchanged.

Reviewed on 2026-08-20 against:
`C:\NOMAD_Test_Output\scientific_catalog_readiness\yz247_yzdev_catalog.sqlite`

---

## Case 1: D356-0316

### Experiment ID

`D356-0316`

### Full processed filename(s)

```
YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG4V-SweepBG1=2_Vb+2to-8_avg1_DR_R_Self.dat
YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG4V-SweepBG1=2_Vb+2to-8_avg1_DR_R_Self.png
```

### Storage-relative path(s)

```
D356 WSe2_AuSplitGate/Processed Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG4V-SweepBG1=2_Vb+2to-8_avg1_DR_R_Self.dat
D356 WSe2_AuSplitGate/Processed Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG4V-SweepBG1=2_Vb+2to-8_avg1_DR_R_Self.png
```

### Reduced candidate raw stem

After stripping the recognized derivative suffix chain (`_avg1_DR_R_Self`):

```
YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG4V-SweepBG1=2_Vb+2to-8
```

### Parsed scientific metadata

- measurement_type: `absorption`
- measurement point / location (`measurement_point_label`): `null`
- temperature_K: `3.6`
- magnetic_field_T: `null`
- excitation_wavelength_nm: `null` (`720nmc` is the center wavelength; `center_wavelength_nm: 720.0`)
- gate configuration: `active_gate_configuration: null`; `fixed_gate_values: {}`; parsed electrical connection `BG2-CG` (electrically tied, bias source)
- counter suffixes: none on the reduced stem; processed suffix chain `_avg1_DR_R_Self` only
- warning: `unsupported electrical expression: FixTG4V-SweepBG1=2`

### Nearby raw-file candidates (human inspection only)

Raw CSV stems under `D356 WSe2_AuSplitGate/Initial Data/`, ranked closest first:

1. `YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG-SweepBG1=2_Vb+2to-8.csv`
2. `YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG=-3-SweepBG1=2_Vb+8to0.csv`
3. `YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG=-4-SweepBG1=2_Vb+8to-2.csv`
4. `YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG=-4-SweepBG1=2_Vb+8to0.csv`
5. `YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG=-6-SweepBG1=2_Vb0to+12.csv`

### Exact differences, token by token (underscore-delimited)

Processed reduced stem tokens:
`[YZ356] [pa] [BG2-CG] [3.6KREF] [720nmc] [0p06sx10] [FixTG4V-SweepBG1=2] [Vb+2to-8]`

| Raw candidate | Token differences vs processed reduced stem |
| --- | --- |
| `FixTG-SweepBG1=2_Vb+2to-8` | token[6] `FixTG4V-SweepBG1=2` vs `FixTG-SweepBG1=2` (processed has extra `4V`) |
| `FixTG=-3-SweepBG1=2_Vb+8to0` | token[6] `FixTG4V-SweepBG1=2` vs `FixTG=-3-SweepBG1=2`; token[7] `Vb+2to-8` vs `Vb+8to0` |
| `FixTG=-4-SweepBG1=2_Vb+8to-2` | token[6] `FixTG4V-SweepBG1=2` vs `FixTG=-4-SweepBG1=2`; token[7] `Vb+2to-8` vs `Vb+8to-2` |
| `FixTG=-4-SweepBG1=2_Vb+8to0` | token[6] `FixTG4V-SweepBG1=2` vs `FixTG=-4-SweepBG1=2`; token[7] `Vb+2to-8` vs `Vb+8to0` |
| `FixTG=-6-SweepBG1=2_Vb0to+12` | token[6] `FixTG4V-SweepBG1=2` vs `FixTG=-6-SweepBG1=2`; token[7] `Vb+2to-8` vs `Vb0to+12` |

### Does the scientific metadata otherwise match?

Partial match only. The closest raw candidate (`FixTG` without a value) matches
every metadata-relevant token except the unparsed `FixTG4V` label. The rule
cannot parse `FixTG4V` as a gate value (warning: `unsupported electrical
expression`), and every raw candidate with a parseable `FixTG=-3/-4/-6` value
carries a different bias range (`Vb+8to0`, `Vb+8to-2`, `Vb0to+12`) than the
processed `Vb+2to-8`, so no candidate confirms the gate configuration or the
measurement range.

### Current provenance and why the deterministic rule abstained

Provenance: directory context `D356 WSe2_AuSplitGate`, `source_type=
storage_directory`, `extraction_method=device_directory_context`,
`review_status=unknown`, `needs_review=1`.

The rule abstained because the reduced stem
`YZ356_pa_BG2-CG_3.6KREF_720nmc_0p06sx10_FixTG4V-SweepBG1=2_Vb+2to-8` does not
exactly equal any raw CSV stem. Linkage is exact-match only and has no fuzzy
fallback, so the `FixTG4V` label mismatch leaves the processed files unflagged
as their own measurement.

---

## Case 2: D356-0317

### Experiment ID

`D356-0317`

### Full processed filename(s)

```
YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_FixTG=-4-SweepBG1=2_Vb0to+12_001_avg1_DR_R_External.dat
YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_FixTG=-4-SweepBG1=2_Vb0to+12_001_avg1_DR_R_External.png
```

### Storage-relative path(s)

```
D356 WSe2_AuSplitGate/Processed Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_FixTG=-4-SweepBG1=2_Vb0to+12_001_avg1_DR_R_External.dat
D356 WSe2_AuSplitGate/Processed Data/YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_FixTG=-4-SweepBG1=2_Vb0to+12_001_avg1_DR_R_External.png
```

### Reduced candidate raw stem

After stripping the recognized derivative suffix chain (`_avg1_DR_R_External`):

```
YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_FixTG=-4-SweepBG1=2_Vb0to+12_001
```

### Parsed scientific metadata

- measurement_type: `absorption`
- measurement point / location (`measurement_point_label`): `null`
- temperature_K: `3.6`
- magnetic_field_T: `null`
- excitation_wavelength_nm: `null` (`720nmc` is the center wavelength; `center_wavelength_nm: 720.0`)
- gate configuration: `active_gate_configuration: null`; `fixed_gate_values: {}`; parsed electrical connection `BG2-CG` (electrically tied, bias source)
- counter suffixes: `_001` on the reduced stem; processed suffix chain `_avg1_DR_R_External` only
- warning: `unsupported electrical expression: FixTG=-4-SweepBG1=2`

### Nearby raw-file candidates (human inspection only)

Raw CSV stems under `D356 WSe2_AuSplitGate/Initial Data/` with `0p1sx10` and
`SweepBG1=2` / `Vb0to+12`, ranked closest first:

1. `YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_FixTG=-6-SweepBG1=2_Vb0to+12_001.csv`
2. `YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_FixTG=-5-SweepBG1=2_Vb0to+12.csv`
3. `YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_FixTG=-6-SweepBG1=2_Vb0to+12.csv`
4. `YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_FixTG=-2-SweepBG1=2_Vb0to+12.csv`

No raw CSV has `FixTG=-4` with the `_001` counter.

### Exact differences, token by token (underscore-delimited)

Processed reduced stem tokens:
`[YZ356] [pa] [BG2-CG] [3.6KREF] [720nmc] [0p1sx10] [FixTG=-4-SweepBG1=2] [Vb0to+12] [_001]`

| Raw candidate | Token differences vs processed reduced stem |
| --- | --- |
| `FixTG=-6-SweepBG1=2_Vb0to+12_001` | token[6] `FixTG=-4-SweepBG1=2` vs `FixTG=-6-SweepBG1=2` only; same counter `_001` and same `Vb0to+12` |
| `FixTG=-5-SweepBG1=2_Vb0to+12` | token[6] `FixTG=-4-SweepBG1=2` vs `FixTG=-5-SweepBG1=2`; no `_001` token (processed length 9, raw 8) |
| `FixTG=-6-SweepBG1=2_Vb0to+12` | token[6] `FixTG=-4-SweepBG1=2` vs `FixTG=-6-SweepBG1=2`; no `_001` token (processed length 9, raw 8) |
| `FixTG=-2-SweepBG1=2_Vb0to+12` | token[6] `FixTG=-4-SweepBG1=2` vs `FixTG=-2-SweepBG1=2`; no `_001` token (processed length 9, raw 8) |

### Does the scientific metadata otherwise match?

Partial match only. The closest raw candidate (`FixTG=-6` with `_001`) matches
every metadata-relevant token except the fixed-top-gate value (`-4` vs `-6`).
The remaining candidates all share the measurement range and wavelength but
differ in gate value and lack the `_001` counter, so no candidate is
unambiguous.

### Current provenance and why the deterministic rule abstained

Provenance: directory context `D356 WSe2_AuSplitGate`, `source_type=
storage_directory`, `extraction_method=device_directory_context`,
`review_status=unknown`, `needs_review=1`.

The rule abstained because the reduced stem
`YZ356_pa_BG2-CG_3.6KREF_720nmc_0p1sx10_FixTG=-4-SweepBG1=2_Vb0to+12_001` does
not exactly equal any raw CSV stem. Linkage is exact-match only and has no
fuzzy fallback, so the `-4` vs `-6` gate mismatch (plus missing `-4` + `_001`
raw) leaves the processed files unflagged as their own measurement.

---

## DECISION

Options (pick exactly one per experiment by editing the matching line):

- `MATCH TO RAW <artifact/path>`
- `LEGITIMATE PROCESSED-ONLY MEASUREMENT`
- `UNKNOWN`

Prefilled decision for this run:

```
UNKNOWN (no human decision supplied this run; catalog unchanged)
```

No relationship was persisted for either experiment during this review run;
the catalog, the two experiments, and the deterministic derivation rule were
not modified.
