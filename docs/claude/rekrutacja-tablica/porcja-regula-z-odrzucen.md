# Porcja dnia: reguła rekrutacji z powtarzanych braków
<!-- indeks: `job_learned_rules`, `rules_from_gaps`, `RULE_MIN` = 3, `MAX_RULES` = 3, `LearnedRule.passes`, `keep_passing` w `_allowed`, `job_rules` w `/me/queue`, „Z odrzuceń: wymagamy…”, `evidence_for` -->

Decyzja Artura z 12.11.2026, raport: https://claude.ai/artifact/PqmctW9taWS8mXwmGfrFSM
(R1, makieta M3). Do 12.11 powód odrzucenia nie zmieniał tego, kogo silnik doda
jutro do tej samej rekrutacji: w Expert Full Stack 13× „brak Angular”, w analizie
systemowej 17× „produkty inwestycyjne”. Od 09.11 ok. 30 z 323 odrzuceń było
kolejnym powtórzeniem tego samego braku.

## Reguły

- **Źródło:** braki kliknięte przy pozycjach (`autofill_feedback.gaps`,
  `porcja-powody-klikane-przy-pozycji.md`). Odrzucenia z samym opisem, bez
  kliknięcia, reguły nie tworzą.
- **Próg:** co najmniej 3 odrzucenia w jednej rekrutacji z tą samą pozycją
  (`RULE_MIN`, bez rozróżniania wielkości liter, jedno odrzucenie liczy pozycję raz).
  Najwyżej 3 reguły na rekrutację, najczęstsze najpierw.
- **Poziom:** same „brak” → wymagamy śladu (pozycja w CV albo umiejętnościach);
  choć jedna „tylko wzmianka” → wymagamy doświadczenia (oś technologii z CV
  z miesiącami stanowisk, `review_batch_facts.evidence_for`). „Za mało lat”
  reguły nie tworzy, bo nie wiemy, ile lat wystarczy.
- **Gdzie działa:** `new_column_autofill._allowed` → `keep_passing`, czyli każde
  dokładanie kart do „Nowych” tej rekrutacji: poranna porcja, „Dodaj kolejnych”,
  dopełnianie. Karty, które już stoją, zostają.
- **Fraza spoza słownika** („produkty inwestycyjne”) nie ma osi technologii, więc
  przy poziomie „doświadczenie” nikt jej nie spełni i rekrutacja przestanie
  dostawać karty, dopóki reguła trwa. To świadome: zespół trzy razy powiedział,
  że bez tego osoba nie pasuje.
- **Ekran:** nad kartą w porcji linia „Z odrzuceń: wymagamy doświadczenia
  w Angular (5×)” (`job_rules` w `GET /api/review-batch/me/queue`,
  `learnedRulesLine`). Jedna linia, bo przy 1280 × 720 dwie spychały „Pasuje”
  pod krawędź ekranu.

Nie ma jeszcze przycisku dla Delivery Leada „ustaw jako krytyczną”: reguła działa
sama, a zmiana krytycznych dalej idzie przez profil Championa.

Testy: `backend/tests/test_job_learned_rules.py`,
`frontend/src/components/v2/review-batch/__tests__/ReviewBatchLearnedRules.test.tsx`.
