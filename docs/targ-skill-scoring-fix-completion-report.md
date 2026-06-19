# Targ — realne dopasowanie kandydata (fix scoringu skilli)

> Fix: „Wrzuć na targ" pokazywał ~28/100 i wszystkie skille kandydata jako czerwone ✗,
> mimo że kandydat je posiada. Przyczyna: silnik scoringu czytał skille kandydata
> tylko ze strukturalnego pola `skills` — puste dla ~99% importowanej bazy.

## Zgłoszenie

Profil kandydata **Jacek Karwowski** (id 25479) → „Wrzuć na targ" → modal „Projekty
dopasowane przez AI" pokazywał:
- Java Backend Developer (senior) — **28/100**, chipy `× spring × postgresql × java`
- Senior Java Developer — **28/100**, chipy `× kafka × hibernate × java`

Kandydat to ewidentny senior Java dev (w trakcie `interview` na „Backend Java developer").
Wszystkie wymagane skille pokazane jako brak (✗) — nieprawda.

## Root cause

Silnik scoringu (`backend/app/services/scoring_service.py`, `_score_skills`) czytał skille
kandydata **wyłącznie** z `candidate.skills` + `candidate.verified_tech` + `candidate.tags`.
Dla importu z Traffita:

| pole | Jacek (id 25479) | cała baza |
|---|---|---|
| `skills` | `[]` (puste) | **49 440 / 49 802 (99,3%) puste** |
| `verified_tech` | `null` | **0 wypełnionych** w całej bazie |
| `tags` | tylko tagi źródła (`traffit_source`) | — |
| `cv_extracted_data.traffit_technologie` | `"JAVA, JDK17, Hibernate, Spring, Springboot, Kafka, … PostgreSQL …"` | **32 152** kandydatów |
| `raw_cv_text` | obecny (4203 zn.) | +12 721 (puste skille, brak traffit tech, ale jest CV) |

Skille kandydata żyją w `cv_extracted_data.traffit_technologie` (lista po przecinku) lub
w `raw_cv_text` — żadnego z nich silnik nie czytał. Efekt: warstwa skilli = **0/30** dla
~99% bazy → każdy wymagany skill → `gap_must` → czerwony ✗ → composite zaniżony (~28/100).

Strona oferty miała już fallback (`_extract_skills_from_champion`: gdy `must_skills` puste,
wyciąga skille z JD/Championa/tytułu). Strona **kandydata nie miała analogicznego fallbacku**.

To inny endpoint niż naprawiany w PR #492 (`api/matching.py`, `/jobs/{id}/ai-matches`).
Targ używa `marketplace_service.scan_candidate_for_top_jobs` → `scoring_service` —
ta ścieżka nigdy nie dostała fixu.

## Fix (`scoring_service.py`)

1. **`_skill_names`** — obsługa stringa: JSON-string (`'["Java","Spring"]'`, ~305 kandydatów
   ma `skills` jako string) dekodowany przez `json.loads`; zwykły string po przecinku przez
   `_split_skill_tokens` (split na `,`/`;`/newline, **nie** na `/` → `CI/CD`, `TCP/IP` całe).
2. **`_skills_from_cv_extracted`** — czyta `cv_extracted_data.traffit_technologie` (string po
   przecinku) lub zagnieżdżoną listę `skills` (TalentRadar).
3. **`_skills_from_raw_cv`** — ostatnia deska ratunku: wyciąga kanoniczne skille z `raw_cv_text`
   przez alias-pattern (ten sam mechanizm co `_extract_skills_from_champion`), cap 4000 zn.,
   tylko gdy taksonomia (`ALIAS_MAP`) załadowana.
4. **`candidate_skill_names`** — priorytet: `skills`+`verified_tech` → CV-extracted → raw CV →
   tags. Fallbacki tylko **DODAJĄ** skille → mogą zamienić fałszywy gap na match, nigdy odwrotnie.
5. `_score_skills` używa `candidate_skill_names(candidate)` zamiast inline ekstrakcji.

Zmiana jest **monotoniczna**: żaden kandydat nie traci punktów; ci z realnymi skillami
(dotąd niewidocznymi) zyskują. Poprawia targ, alerty marketplace, widget „Sugerowane
rekrutacje" oraz listę „AI matche kandydatów" — wszystkie idą przez `scoring_service`.

## Weryfikacja

- **Repro na realnych danych Jacka** (id 25479) — warstwa skilli **0,0/30 → 20,0/30**,
  chipy `java/spring/postgresql` i `java/kafka/hibernate` z ✗ → ✓. Composite ~28 → ~48.
- **Testy:** `tests/test_scoring_service.py` +14 (stringified JSON, traffit_technologie,
  raw_cv fallback, priorytet, regresja Jacka). `73 passed` (scoring + matching_skills);
  `103 passed` w szerszym przebiegu. Jedyny FAIL (`test_significant_update_none_vs_empty_list`)
  jest **pre-existing** (potwierdzone na czystym HEAD), nie dotyczy tej zmiany.
- **ruff** — czysto.
- **Efekt uboczny alertów marketplace** — pula targu = **9 osób**, próg powiadomień = **70/100**,
  dedup per para `(candidate_id, job_id)`. Brak ryzyka zalewu (Jacek ~48 < 70). Sam display
  targu (`scan_candidate_for_top_jobs`) nie ma progu → korzysta od razu.

## Pliki

- `backend/app/services/scoring_service.py` — `_split_skill_tokens`, `_skill_names` (str),
  `_skills_from_cv_extracted`, `_skills_from_raw_cv`, `candidate_skill_names`, `_score_skills`.
- `backend/tests/test_scoring_service.py` — +14 testów.

## Znane ograniczenia / follow-up

- **Backfill (opcjonalny):** można dodatkowo wypełnić strukturalne `skills` z
  `traffit_technologie` (32k kandydatów) — poprawiłoby też wyświetlanie chipów na profilu
  i embeddingi. Świadomie poza zakresem (write do 32k wierszy + re-embedding); runtime
  fallback rozwiązuje problem scoringu natychmiast i bez migracji.
- **Pre-existing test fail** `test_significant_update_none_vs_empty_list_equivalent`
  (`marketplace_service.is_significant_job_update`: `None` vs `[]`) — zgłoszony osobno.
