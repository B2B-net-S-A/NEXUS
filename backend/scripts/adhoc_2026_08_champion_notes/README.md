# Ad-hoc: import Championów + fakty z notatek (08.2026) — archiwum

Skrypty jednorazowego importu z 13–14.08.2026, przeniesione 1:1 z `/root/` na
serwerze prod (do tej pory żyły TYLKO tam — każda odbudowa serwera by je
skasowała). **To archiwum przebiegu, nie narzędzia do ponownego użycia** —
ścieżki `/tmp/*.jsonl` i `sys.path.insert("/app")` zakładają uruchomienie
w kontenerze backendu przez `docker exec`.

| Skrypt | Rola w imporcie |
|---|---|
| `champ_parse_v3.py` | 1095 plików Championa (DOCX/PDF) → Haiku → JSONL (7 sekcji: must/nice, stawka, lokalizacja+tryb, języki, start, seniority, sektory, screening, keywords, OFFLIMIT) |
| `champ_ingest.py` | JSONL → `jobs.champion_profile` (949 ofert) + FILL_EMPTY must/nice + reindeks ofert + `mark_stale_for_job` |
| `champ_supersede.py` | Champion nadpisuje ubogie auto-must (620 ofert; stare listy w `_superseded_must_skills` — odwracalne) |
| `notes_extract_full.py` | v1: pełny korpus notatek → stawki/dostępność/preferencje/veta (13,9k kandydatów) |
| `notes_extract_v2.py` | v2: rozszerzony schemat → skills_evidenced z dowodami, zaangażowanie, relokacja, uprawnienia |
| `notes_ingest.py` | v1 → `_notes_insights` + `expected_rate_hourly` FILL_EMPTY (8 853 stawek) + raport wet (1 348) |
| `notes_v2_ingest.py` | v2 → merge insights + skills APPEND z dedupem (50,4k) + `years_it_experience` FILL_EMPTY |
| `notes_fill_columns.py` | `_notes_insights` → kolumny dostępności (notice_period 4 237, availability_date 1 371, status 2 747) |

**Następca produkcyjny:** cykliczna świeżość notatek żyje w
`app/services/notes_insights_extractor.py` (unia promptów v1+v2, jedna
polityka zapisu) + `app/tasks/notes_insights_sync.py` (pętla z fingerprintem —
płacą tylko kandydaci ze zmienionymi notatkami). Zmiany w polityce zapisu rób
TAM, nie tutaj.

Kontekst decyzji i wyniki pomiarów: `docs/` (raporty champion/notes) oraz
pamięć projektu (`champion-notes-import-complete-2026-08-14`,
`champion-signals-go-flipped-2026-08-15`).
