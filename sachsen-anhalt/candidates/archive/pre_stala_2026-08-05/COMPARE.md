# ST candidates: pre-StaLa archive vs official (2026-08-05)

Official source: [https://statistik.sachsen-anhalt.de/themen/gebiet-und-wahlen/wahlen/landtagswahl-2026/wahlvorschlaege](https://statistik.sachsen-anhalt.de/themen/gebiet-und-wahlen/wahlen/landtagswahl-2026/wahlvorschlaege)
Excel: `https://statistik.sachsen-anhalt.de/fileadmin/Bibliothek/Landesaemter/StaLa/startseite/Themen/Wahlen/Tabellen/Auswertung_VOeff_FgMI.xlsx`

Old files kept in this directory (`direktkandidaten_2026.csv`, `listenkandidaten_2026.csv`, `lists/`).

## Direkt
- Old: 270 → New: 284
- Same (normalized): 261
- Added: 14, Removed: 0, Name changes: 9

### Coverage
- `afd`: 37/41 → **41/41**
- `bsw`: 24/41 → **27/41**
- `cdu`: 41/41 → **41/41**
- `fdp`: 39/41 → **41/41**
- `gruene`: 41/41 → **41/41**
- `linke`: 41/41 → **41/41**
- `spd`: 41/41 → **41/41**
- `fw`: 6/41 → **11/41**

### Added
- WK 6 `fw`: **Kay Gericke**
- WK 10 `afd`: **Oliver Kirchner**
- WK 10 `bsw`: **Vinzenz Louis Mühlbach**
- WK 11 `afd`: **Hagen Kohl**
- WK 12 `afd`: **Christian Mertens**
- WK 12 `bsw`: **Lenny Werner Wapenhans**
- WK 13 `afd`: **Ronny Kumpf**
- WK 13 `bsw`: **Hugo Boeck**
- WK 24 `fdp`: **Maximilian Frey**
- WK 24 `fw`: **Norman Unger**
- WK 25 `fdp`: **Marcus Hillwig**
- WK 25 `fw`: **Maik Mattheis**
- WK 28 `fw`: **Ronny Schneider**
- WK 37 `fw`: **Yvonne Krause**

### Removed
- (none)

### Name changes
- WK 1 `fdp` (expand/middle): Thomas Mothes → **Thomas Dietmar Mothes**
- WK 2 `spd` (expand/middle): Skady Herkenrath → **Skady Luisa Herkenrath**
- WK 10 `fdp` (expand/middle): Dr. Lydia Hüskens → **Dr. Lydia Maria Hüskens**
- WK 10 `gruene` (DIFFERENT): Rico Hermann → **Rico Herrmann**
- WK 10 `linke` (expand/middle): Noah Biswanger → **Noah Elias Biswanger**
- WK 24 `gruene` (DIFFERENT): Bea Lindhorst → **Beatrice Lindhorst**
- WK 24 `linke` (expand/middle): Thomas Lippmann → **Thomas Erich Herbert Lippmann**
- WK 28 `fdp` (expand/middle): Guido Kosmehl → **Guido Lars Kosmehl**
- WK 29 `fdp` (expand/middle): Dr. Maximilian Georg Philipp → **Dr. Maximilian Philipp**

## Listen (seed CSVs)

| Party | Old → New | Notes |
|-------|-----------|-------|
| SPD | 40 → 40 | LP39 was missing on party site (Paul Kley); Nils Johannson now LP40 |
| AfD | 60 → 59 | OCR party list wrong from ~LP45 (André Frenzel dropped; cascade shift) |
| CDU | 50 → 50 | LP38 spelling: Schlotmann-Jeschke → Dr. Daniel Schlothmann-Jeschek |
| Linke | 34 → 34 | middle-name expansions only |
| Grüne | 20 → 20 | middle-name expansions only |
| FDP | 20 → 20 | middle-name expansions only |
| BSW | 23 → 22 | Frank Burgsdorf dropped; lower ranks shifted; length −1 |

## Notes
- Official Excel typo `AI-Chakmakchi` corrected to `Al-Chakmakchi`.
- Middle names / expanded legal names from StaLa kept as authoritative.
- Grüne WK 10: party site had `Rico Hermann`; official is `Rico Herrmann`.
- `fw` Direkt (11 WKs) and `lists/fw.csv` included from StaLa; listen builder still only uses main parties.
