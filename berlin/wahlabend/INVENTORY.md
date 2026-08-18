# Berlin Wahlabend / Nowcast — Dateninventar

Ziel: **Nowcast** (Struktur + Historie + räumliche Nähe) für AGH 2026,
**Evaluation** mit `_W_`-Zeiten + simulierten Meldeordnungen, **Zeitstrahl-UI** für Nowcasts zu jedem t.

Stand: 2026-08-07 (URL-Probe).

## Produkt

| Baustein | Beschreibung |
|----------|----------------|
| Nowcast | Land / Bezirk-Anteile für **CDU/SPD/Linke** (Bezirkslisten) / WK |
| Institutionen | **Direkt (Erststimme)**, Einzug (5 % / Grundmandat), **Parlamentsgröße** (BE-Formel) |
| Prior | Pre-Election Forecast + Historie (AGH23/16, BTW25) auf 2026-Gebieten |
| Bias-Korrektur | Strukturähnlichkeit, Nachbarschaft, Urne vs Brief |
| Evaluation | Meldeordnungen × **Nowcast-Methoden** (prior / naive / global / local / full) |
| UI | Zeitstrahl + Methoden-Vergleich; **WK-Rennen** (Vorhersage t, P(Führung), Call, Endsieger, Platzhalter); WK-Überblick, Größe(t)-Kurve, Listen-Einzug |

## Modell-Check (2026-08-07)

- **Kein Leakage** gefunden: Prior = Polls (vorab), L1 = 2016, Struktur = 2023-Merkmale; Wahrheit nur für gemeldete WBs.
- **Parameter-Sensitivität** (hl 0.05–0.20, mix_local 0–1, k 10–80, rep_power 1.25–2): MAE-Änderungen ≤ ~0.1 PP → Leistung kommt aus dem Mechanismus, nicht aus Tuning. Geringes Hyperparameter-Overfitting.
- **Aber:** Design + Eval auf derselben Wahl (AGH2023). Echter Out-of-sample-Test = Backtest auf **BTW2025-`_W_`** (Daten liegen vor) → nächste Schritte.
- **Band-Kalibrierung** (Ziel ~80 %, soft): Land-Faktor 1.3→1.0 + idiosynkratischer Zuschlag `resid_rms/√n_open` für kleine Gebiete. Coverage jetzt: Land 90–100 %, Land+WK 82–92 % (Ausreißer `actual_times` 73 % — geklumpte Nachbearbeitungs-Reihenfolge, dokumentiert).
- **Calls** (P(Führung) ≥ 99 % + erste Meldung im WK): **Erststimmen-Nowcast** vs. Erst-Sieger.
  Call ist richtig oder falsch — kein Zweit-Proxy, keine Splitting-Ausrede.
- **Einzug/Größe-Unsicherheit**: Monte Carlo (48 Draws) über das Band → p10/p50/p90 für Größe, Sitze, Listensitze (je Bezirk bei CDU/SPD/Linke). Direktmandate im MC = Erst-Nowcast-Führer.

## Direkt · Einzug · Größe (am Nowcast)

Heute im Replay (`eval.institutions`):

| Größe | Direkt | Einzug |
|-------|--------|--------|
| `allocate_be` aus Nowcast-Zweit + Erst-Direktmandate → Größe + Sitze | Erststimmen-Nowcast je WK vs. Erst-Sieger 2023 | ≥5 % **oder** ≥1 Direkt |

**Nächste Produktseiten** (wie Pre-Election `/preview/direktmandate/` und `/preview/einzug/`):

1. **Direkt am Wahlabend** — Live-UX für Erst-Nowcast + Call-Karte 78 WK.
2. **Einzug am Wahlabend** — Kandidaten-Sim (`candidate_entry_sim`) an Nowcast-Draws (Land + Direkt + Unsicherheit).
3. **Parlamentsgröße** — bereits im Zeitstrahl; optional eigene Kurve Größe(t) / Überhang.

Bis dahin: Institutionen-Block auf `/preview/wahlabend/` ist die gemeinsame Eval-Oberfläche.

## Live-Feeds (Wahlabend)

Muster unter `https://www.wahlen-berlin.de/wahlen/…/Datenexport_…`:

| Suffix | Bedeutung |
|--------|-----------|
| `_A_BE.csv` | Aggregate (Land, Bezirk, AGH-WK, …) + `Datum`/`Zeit` des **Abzugs** |
| `_W_BE.csv` | **Wahlbezirke** + `Datum`/`Zeit` pro Zeile |

AGH 2026-URLs analog zu 2023 erwarten, sobald AfS sie freischaltet.
Poll ≥ 2 Min. AfS hochrechnet **nicht**.

### Verfügbare `_W_` / `_A_` Exporte (jetzt online)

| Wahl | `_W_` | `_A_` | Basis-URL |
|------|-------|-------|-----------|
| AGH 2023 | Erst + Zweit | Erst + Zweit | `…/BE2023/AFSPRAES/agh/` |
| BTW 2025 | Erst + Zweit | Erst + Zweit | `…/BU2025/afspraes/` |
| EU 2024 | Stimme | Stimme | `…/EU2024/AFSPRAES/` |
| AGH 2021 / 2016 / … | — | — | kein AFSPRAES-`Datenexport_*` mehr |

Beispiel AGH2023 Zweit `_W_`:
`https://www.wahlen-berlin.de/wahlen/BE2023/AFSPRAES/agh/Datenexport_AGH2023_Zweitstimme_W_BE.csv`

**Hinweis Zeiten:** Im eingefrorenen Endstand sind `Datum`/`Zeit` oft **Nachbearbeitung**
(AGH2023: ab 13.02., Masse 20.–21.02.; Wahl war 12.02.) — nicht zwingend Wahlnacht-Eingang.
Für Evaluation: **Meldezeiten simulieren**; echte Nacht-Snapshots (lokal) optional kalibrieren.

## Endgültige Wahlbezirksergebnisse (XLSX)

Quelle: [AfS Wahlbezirksergebnisse](https://www.statistik-berlin-brandenburg.de/wahlen-berlin-wahlbezirksergebnisse)

| Wahl | Datei | Bemerkung |
|------|-------|-----------|
| AGH+BVV 2023 | `DL_BE_AGHBVV2023.xlsx` | Primär |
| AGH+BVV 2021 | `DL_BE_AGHBVV2021.xlsx` | ungültig, trotzdem nutzbar für Struktur/Transfer |
| AGH+BVV 2016 | `DL_BE_EE_WB_AH2016.xlsx` | |
| AGH+BVV 2011 | `DL_BE_AB2011.xlsx` | |
| älter | `DL_BE_AB2006` … `AH1990` | nur bei Bedarf |

Lokal bereits: `berlin/raw/be_agh2023.xlsx`.

## Umschlüsselung auf **2026**-Wahlbezirke (AfS, fertig)

Kein eigenes Areal-Weighting nötig für diese zwei:

| Datei | Inhalt |
|-------|--------|
| `DL_BE_AGH2026_AGH2023.xlsx` | AGH2023 Zweit → 2026-WB (~4114 Zeilen, W+B) |
| `DL_BE_AGH2026_BT2025.xlsx` | BTW2025 Zweit → 2026-WB |

Overlap mit Struktur-Adressen (Urne): ~2541/2546. Briefwahl extra in Remap.

Für **2016 → 2026** (und ältere): selbst areal-weighted oder AfS-Zwischen-Remaps
(`DL_BE_AGH2023_AH2016.xlsx` auf 2023er Gebiete, dann 2023→2026).

## Strukturdaten

| Datei | Ebene |
|-------|-------|
| `DL_BE_AH2026_Strukturdaten.xlsx` | 2026-Wahlbezirke, ~80 Felder (Alter, Migration, Religion, …) |
| `DL_BE_AGH2023_Strukturdaten.xlsx` | 2023 (via BE2023 Wahlstrukturdaten) |
| `DL_BE_AH2016_Strukturdaten.xlsx` | 2016 |

2026-Struktur: v. a. **Urnen** (`Adresse` wie `01W101`); Briefwahl über Zuordnung `Briefwahlbezirksnummer`.

## Geometrien

| Jahr | Quelle | Status |
|------|--------|--------|
| AGH 2026 UWB/BWB/AWK | GDI WFS `wahlgebiete_agh2026` (`agh2026_uwb`, `agh2026_bwb`, `agh2026_awk`) | nutzbar |
| AGH 2026 Shapefile | `RBS_OD_UWB_AH26.zip` (Open Data) | CDN liefert oft HTML-Shell — WFS oder manueller Download |
| AGH 2021 UWB | `RBS_OD_UWB_AH21.zip` | gelistet |
| AGH 2016 UWB | `RBS_OD_UWB_AGH_09_2016.zip` | gelistet |
| AGH 2023 | Wahllokale (Punkte) `RBS_OD_Wahllokale_AH23.zip`; UWB-Polygone prüfen | |
| BTW 2025 UWB | `RBS_OD_UWB_BT25.zip` | gelistet |

Lokal: Wahlkreis-GeoJSON `berlin/geo/ltw_wahlkreise_be.geojson` (keine WB-Polygone bisher).

**Areal-weighted interpolation** wenn Shapefiles differieren und kein AfS-Remap existiert
(2016→2026, ggf. 2021→2026). Briefwahl: nicht über Fläche, sondern über Zuordnung/Historie.

## Nowcast-Skizze

```text
Prior_i          = f(forecast, Historie_2026, Struktur_i)
Residual_j       = beobachtet_j - Prior_j    für gemeldete j
δ̂_i             = Σ_j w(i,j) · Residual_j   w = Struktur + Distanz + gleicher Bezirk/WK
Nowcast_i        = Prior_i + δ̂_i            (Unausgezählt)
Fix              = gemeldete Bezirke
Aggregate        → Land / Bezirksliste / WK-Erst → Einzug-Sim
```

Urne/Brief getrennt shrinken. Früh in der Nacht stark zum Prior.

## Evaluation & Zeitstrahl

1. Ground truth = Endstand auf 2026-WB (Remap + Live-Endstand 2026).
2. **Meldeordnung**: Default `actual_times` aus `_W_` Datum/Zeit; plus simulierte Szenarien (random, Urne→Brief, Größe, „grüne/CDU-Kieze früh“).
3. Optional: lokale 2023-Nacht-Snapshots als bessere Chronologie, falls `_W_`-Zeiten nur Nachbearbeitung sind.
4. Für jeden t: Nowcast nur mit Info ≤ t → Error-Kurve (Landanteile, Mandate, Einzug).
5. UI: Slider über t, Karte (gemeldet/offen), Kandidaten-P(Einzug).

## Implementierung (MVP)

```bash
make wahlabend-fetch     # → berlin/wahlabend/raw/
make wahlabend-nowcast   # → output/wahlabend_nowcast_replay.json
./scripts/deploy_pages_preview.sh
# Preview: /preview/wahlabend/
```

| Datei | Rolle |
|-------|-------|
| `code/wahlabend_nowcast.py` | Baseline+Swing, simulierte Meldeordnung, Replay-JSON |
| `scripts/fetch_wahlabend_data.sh` | Rohdaten spiegeln |
| `website-integration/.../preview/wahlabend/` | Zeitstrahl-UI |

Eval: AGH2023 Wahrheit, Baseline = AGH2016 auf 2023er WB. Offene Bezirke =
baseline + shrunk swing (global + Bezirk×Urne/Brief + Struktur-Nachbarn).

## Nächste Schritte

1. 2026-Live-Pfad: Remaps AGH23/BTW25 + Struktur 2026 als Baseline/Prior
2. **Backtest BTW2025** (`_W_` liegt vor): gleiche Pipeline, andere Wahl → echter Out-of-sample-Test gegen In-Sample-Tuning
3. WFS 2026 UWB → Nachbarschaft über Geometrie
4. AGH2016→2026 areal remap für längeren Backtest
5. **Direkt-Seite am Nowcast** — Live-UX / Call-Karte (Erststimme; Fehl-Calls = Bug, keine Ausrede)
6. **Einzug-Sim** an Nowcast-Draws koppeln (Kandidaten-P statt Platz-Quantile)
7. Echte Nacht-Snapshots archivieren sobald AFSPRAES 2026 live ist
8. state-models lead0/1 statt Poll-Mean als π₀

## Nicht verwechseln

- `_A_`-`Zeit` = Export-Zeitstempel der Aggregate, nicht Meldezeit eines WB
- Eingefrorene `_W_`-`Zeit` ≠ zuverlässige Wahlnacht-Chronologie
- Testdaten-Mail AfS = Muster für **Live**-CSV-Format (BTW/EU-PMs); AGH `_W_` liegt oft unlinked unter AFSPRAES
