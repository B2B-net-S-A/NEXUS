# Świeżość umiejętności — ponad 3 lata to „?”, nie „✓” (27.10.2026)
<!-- indeks: `services/skill_freshness.py`, `last_used_year` w wymaganiach propozycji i pełnego przeglądu, „angular · 2020”, `evidence_basis = stale_profile_signal` -->

Zgłoszenie Delivery Leada (ciąg dalszy „Inna rola”, `inna-rola-niz-rekrutacja-tester-przy-programiscie.md`):
tester z Angularem z lat 2019–2020 (testy w Protractorze) miał „✓ angular” przy
„Full Stack Developer (Java, Angular)”. Decyzja Artura 27.10.2026: technologia,
której kandydat ostatnio używał ponad 3 lata temu, nie jest spełnionym
„musi mieć” — jest „?” z rokiem, rekruter pyta w rozmowie. Wag „Dop.” nie
ruszamy (zmienia je Head of Recruitment w panelu po pomiarze).

## Reguły

- **Gdzie:** `requirement_contract.evaluate_requirements` — wymagania pełnego
  przeglądu bazy (`candidate_search_worker` → `evidence.requirements`), a z nich
  propozycje w oknie „Kandydaci do dodania”, „musi mieć X/Y” i próg 80% must
  przy innej roli w nocnym przeglądzie (`role_family`). Punkty „Dop.”
  (`scoring_service._score_skills`) i bramka krytycznych bez zmian.
- **Daty:** `last_used` z `candidates.skills`, `cv_extracted_data.skills`
  i `cv_extracted_data.skill_timeline` (oś z doświadczenia). Liczy się
  NAJPÓŹNIEJSZA znana data ze wszystkich źródeł — rok przy „?” też. Przy
  ręcznie poprawionej liście (`skills_manually_curated`, `_manual_override_skills`)
  tylko daty z samej listy.
- **Granica:** starsze niż 36 miesięcy od dziś (`business_today`) = „?”;
  dokładnie 3 lata jeszcze „✓”. Sam rok = grudzień tego roku (na korzyść
  kandydata: 2023 w październiku 2026 to „✓”, 2022 to „?”). `present` = dziś.
  Brak daty albo data nieczytelna = bez zmian („✓”) — brak daty nie jest
  dowodem, że technologia jest stara.
- **Wzmianka w CV nie przebija daty** — to ta sama, stara pozycja CV. Grupa
  „A lub B” jest „✓”, gdy którakolwiek opcja jest świeża albo bez daty.
  Weryfikacja rekrutera (`reviewed_group`) wygrywa z datą.
- **Kształt:** wiersz „?” z datą ma `last_used_year` (liczba) i
  `evidence_basis = "stale_profile_signal"`, `matched = []`.
  `job_proposals._REQUIREMENT_KEYS` przepuszcza `last_used_year` (sama
  liczba, bez kontekstu z CV). Front: `ProposalRequirement.lastUsedYear`,
  w panelu osoby „? angular · 2020”, w chipach powodu „angular · 2020” jako
  „zapytaj”, w wynikach pełnego przeglądu „ostatnio używane w 2020 — do
  potwierdzenia”.
- **Propozycje zapisane wcześniej** zmieniają się dopiero po kolejnym
  przeglądzie bazy (dowód jest zamrożony przy propozycji).
- **Skala w dniu zmiany** (staging z 22.10.2026, otwarte propozycje
  w otwartych rekrutacjach): 1 332 z 130 838 „✓ musi mieć” (1,0%) przechodzi
  na „?”, w 947 z 31 077 propozycji, w 84 rekrutacjach. Najczęściej: SQL,
  Java, Jenkins, Jira, Selenium, Git, Docker, Spring, Angular.
- **Pomiar kolejności** (`python -m scripts.eval_manual_search_order --jobs 120
  --rerank-top 200`, staging, przed i po): tabele identyczne — kolejność
  produkcji 86,7% rekrutacji z właściwą osobą na 1. stronie, 51,4% właściwych
  w top 50, MRR 0,416. Zmiana nie dotyka „Dop.”. Zmiana granicy albo źródeł
  dat = ten sam pomiar i to samo liczenie ✓→? przed i po.
