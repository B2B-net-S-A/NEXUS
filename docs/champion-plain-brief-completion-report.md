# „Champion po ludzku” i ściąga do rozmowy — raport (29.09.2026)

Makiety: https://claude.ai/artifact/WEVyKuavTdd8JVggXQ9mD3 (v7). Kontrakt API:
`docs/champion-plain-brief-contract.md`. Reguły: sekcja w `CLAUDE.md`.

## Co powstało
- **Blok „Po ludzku”** na górze Podglądu Championa (`components/champion/plain/`):
  rola z historią (liczba rekrutacji, zatrudnień, stanowiska zatrudnionych — bez
  stawek), jedno zdanie, „Przykład z codzienności”, o kliencie, czym będzie się
  zajmować, słowniczek stacku (tabela na całą szerokość), pytania z sekcji 6
  przepisane zrozumiale („Po co pytasz / Dobra odpowiedź / Odpada, gdy”).
- **Ściąga do rozmowy** w doku osoby (Screening/Nowi): 30 s o projekcie ze stawką
  i klientem, „Kandydat pyta”, 3 pytania z profilu, „Dopisz do »Do dopytania«”.
- **Biblioteka ról** (Ustawienia → Rekrutacja) i pola „po ludzku” w Słowniku
  umiejętności; poprawki: admin + Head of Recruitment, z historią zmian.
- **Opis klienta z internetu** w karcie klienta (`about_for_candidate_origin=web`).
- Backend: migracja 0402 (`plain_terms`, `role_profiles`, `job_plain_briefs`,
  `plain_knowledge_events`, `jobs.role_profile_id`, pola karty), research w
  internecie (F26), dopasowanie roli bez AI, teksty rekrutacji z kontrolą
  ugruntowania, trasy GET/POST/PUT, skrypt `scripts/build_plain_knowledge.py`.

## Sprawdzone
- Backend lokalnie (Python 3.12, bez bazy): testy jednostkowe `test_plain_knowledge.py`
  i kontrakty (rejestr AI, lustra entrypointu, sekcje, limity, własność kolumn,
  przewodniki) — zielone. Testy z bazą biegną w CI.
- Frontend: 492 testy vitest, `tsc`, eslint — zielone. Harness `/preview/plain-brief`
  obejrzany przy 1280 px (równe kolumny słowniczka) i zmierzony przy 390 px
  (brak przewijania w bok).
- Przegląd kodu: 4 problemy blokujące naprawione (dwie głowy migracji, 500 po
  awarii modelu, hasło zawieszone w `researching`, luki w ugruntowaniu) — z testami.

## Czeka po wdrożeniu
1. `scripts/build_plain_knowledge.py --plan … --review …` na produkcji → przegląd
   arkusza przez Artura → `--write-seed` (technologie i role do repo, osobny PR).
2. `--apply-clients` (opisy klientów bez opisu) i `--assign-roles` na produkcji.
3. Pomiar tekstów rekrutacji (20 profili, Luna vs Sonnet) przed ewentualną zmianą modelu.

Do tego czasu baza wiedzy buduje się sama: otwarcie otwartej rekrutacji uzupełnia
brakujące hasła, rolę i opis klienta (najwyżej 3 researche w żądaniu, reszta w tle).
