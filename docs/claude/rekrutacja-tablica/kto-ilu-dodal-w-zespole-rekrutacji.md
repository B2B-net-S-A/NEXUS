# „Kto ilu dodał” w okienku „Zespół rekrutacji” (16.11.2026)
<!-- indeks: dodania do rekrutacji per osoba (pierwszy wpis pary), nie osoba karty; tabela pod zespołem, nie pasek; zera dla zespołu; automat osobno -->

Prośba z zespołu z 16.11.2026: po wejściu w rekrutację widać, który
rekruter ilu kandydatów dodał. Decyzje Artura z 16.11.2026 po makietach
A/B/C na stagingu (wybrany wariant C, liczyć dodania).

## Reguła

- **Gdzie:** tabela pod listą zespołu w okienku faktu „Rekruter”
  (`JobRecruiterFact` → `AddedToJobTable`), tylko na Tablicy i tylko z
  wczytaną Tablicą. Nie pasek w nagłówku i nie kafel: Artur odrzucił
  warianty A (pasek z imionami) i B (kafel), bo nagłówek przy 1280 × 720
  jest pełny. Okienko przewija się w środku, gdy jest wyższe niż ekran.
- **Co liczy:** dodania do TEJ rekrutacji od otwarcia, także odrzuconych
  i wycofanych: osoba z pierwszego wpisu etapu pary
  (`added_to_job_by_id` z `GET /api/pipeline/kanban/{job_id}`). Liczy front
  w `lib/board-added-summary.ts`, bez osobnego API.
- **To nie jest filtr „Kto dodał”.** Filtr (`lib/board-added-by.ts`) liczy
  osobę karty („Biorę”, weryfikacja, „Prowadzi”) i tylko osoby w toku. Na
  jednej rekrutacji (789206, staging 16.11) filtr dawał rekruterowi 29, a w
  bazie nie dodał nikogo — brał do telefonu osoby z automatu. Dlatego wiersz tabeli
  nie włącza filtra i obu liczb nie łączysz w jedną.
- **Wiersze:** najpierw osoby, od największej liczby dodań; rekruterzy
  pracujący przy rekrutacji (`workingRecruiters`) bez dodań zostają z zerem
  (bursztynowe), żeby było widać, kto jeszcze nikogo nie dodał. Na końcu
  „Automat „Nowi”” (`entry_source = "system"`) i „Bez danych” (stary wpis
  bez osoby) — nie liczą się do „ludzie”.
- **Kolumny:** Dodał · 7 dni (dziś i sześć dni wstecz, kalendarz firmy) ·
  W toku · Zweryf.+ (w toku od „Zweryfikowanego”) · U klienta (w toku od
  „CV wysłane”). Ostatnie dwie liczą tylko osoby w toku: o zamkniętych
  Tablica wie, gdzie skończyli, a nie jak daleko doszli. Gdyby trzeba było
  „doszli kiedykolwiek”, liczy to backend z historii `candidate_stages`.

## Poza Tablicą (decyzja 16.11.2026)

Artur chce tej samej liczby także na pulpicie HoR/DL (tabela zespołu dnia),
w Daily (nowe profile rozbite na osoby) i w Insights → Raporty (kolumna obok
„Kandydaci”, która liczy nowo utworzone profile, nie dodania). To osobne
zmiany z liczeniem w backendzie (`recruitment_processes.opened_by_user_id`,
`services/new_profiles.py`). Do ligi (punktów) dodania nie wchodzą.
