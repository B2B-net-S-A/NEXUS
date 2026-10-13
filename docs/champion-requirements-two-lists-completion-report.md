# Wymagania Championa: dwie listy i uczciwe wyszukiwanie — raport (13.10.2026)

Decyzja Artura 13.10.2026: wariant A (D1–D6) i poprawki błędów. Pomiar i makiety:
https://claude.ai/artifact/8qx5WrueDSLHht7VezW2L5. Reguły: `docs/claude/rekrutacja-tworzenie/dwie-listy-wymagan-slowa-i-rozmowa.md`.

## Co było źle (pomiar na produkcji, 206 opublikowanych rekrutacji)

- 30% pozycji „musi mieć” (554 z 1 818) to zdania, kategorie, branże, języki, role, miękkie.
- W propozycjach AI takie pozycje miały „? brak potwierdzenia” w 95–100% przypadków.
- „doświadczenie w przetargach” jako słowo kluczowe: 1 osoba z 65 924; „przetarg*”: 727.
- Krytyczne frazy ukrywały prawie wszystkich (789128: „architektura chmury” → 0 osób w „Szukaj w bazie”).
- 5 z 6 rekrutacji z samymi zdaniami w must nie miało żadnej propozycji AI.
- Nawias kasował technologię („SQL (bardzo dobra znajomość)”: 0 z 316 propozycji z SQL spełnionym).
- 34 otwarte rekrutacje: silnik czytał kolumnę z prozą zamiast Championa.

## Co zmieniono

| Część | Stan | Dowód |
|---|---|---|
| D1 dwie listy (`experience.skills`, język w `basics.language`) | zrobione | `tests/test_experience_skills.py` |
| Bramka: nawias, wstęp, „Top 10” (`critical-v12`) | zrobione | `tests/test_must_gate_terms.py`; eval_matching przed/po bez zmian (P@5 0,1700, R@20 0,1105, MRR 0,3943, nDCG@10 0,1405) |
| Czytanie frazy (`requirement_phrase`) + `readings` | zrobione | `tests/test_requirement_phrase.py`, `test_job_intake_requirement_routes.py` |
| D3 serwer: zdania z wierszy do rozmowy przy zapisie | zrobione | `tests/test_separate_talk_items.py` |
| D3/D2 front: decyzja w edytorze, ostrzeżenie i potwierdzenie < 20 osób | zrobione | `RequirementRowsEditor.test.tsx`, `requirement-rows.test.ts`, `job-request-intake.test.ts` |
| D6 komunikat blokady `search` | zrobione | lustro `job-readiness-blockers.json` |
| B3/B4/D5 propozycje i karta | zrobione | `tests/test_proposal_talk_checks.py`, `ProposalPanel.test.tsx`, `PersonPreview.test.tsx` |
| P3 „Szukaj w bazie” | zrobione | `AddCandidatesPanel.test.tsx`, `job-search-filters.test.ts` |
| D4 „Wymagania do poprawy” (0438, trasy, pulpit, baner) | zrobione | `tests/test_requirement_cleanup.py`, `RequirementFixesSection.test.tsx`, `RequirementProposalDialog.test.tsx` |
| Przewodniki Jarvisa, wzorzec bramek tras, dokumentacja | zrobione | `check_stamps.py`, `authz_golden/jobs.json` |

Bramka czyta teraz 1 005 zamiast 981 pozycji must w 170 otwartych rekrutacjach z must; rekrutacji
z co najmniej jednym słowem bramki 145 zamiast 139. Sonda D4 na produkcji: 133 z 202 otwartych
rekrutacji dostanie propozycję (zdania 96, brak słów do szukania 34, proza w kolumnie 34, nawias 6,
krytyczne spoza bramki 3).

## Rozjazdy z makietami

- Bez „+ pytanie”: pozycja z listy i tak jest punktem „Sprawdź w rozmowie” w screeningu.
- Język nie jest nowym rodzajem — trafia do pola „Język pracy” (jedno źródło).
- P2 bez „zostanie N” dla każdej alternatywy — liczba ze słów kluczowych to nie bramka AI.
- „Rozdziel teraz” zamiast automatycznego rozdzielania w trakcie pisania.
- Panel „Rekruter sprawdza w rozmowie” stoi pod wierszami (nie obok) — przy 1280 px obok byłoby za ciasno.

## Do sprawdzenia po wdrożeniu

- `/api/health` → SHA z maina; `/api/health/deep` → `requirement_cleanup_decisions` healthy.
- Propozycja 789128 przez API; lista na pulpicie DL-a.
- Przeklikanie w Chrome (zalogowana produkcja): `/preview/new-job?state=readings`, `/preview/recruitment-v3`,
  `/preview/job-detail?sources=search`, `/preview/custom-dashboard`, Profil Championa rekrutacji testowej
  (bez zapisu).
- Nocne przeglądy: podbicie `critical-v12` unieważnia zapisane przeglądy całej bazy — odświeżą się
  w ok. 8 nocy (limit 25/noc); skrzynka propozycji działa cały czas.
