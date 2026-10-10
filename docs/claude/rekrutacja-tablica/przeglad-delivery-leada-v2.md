# Przegląd Delivery Leada v2 (D6, D9, D10, 08.10.2026)

Decyzje Artura D6, D9, D10 z planu `docs/candidate-path-d1-d10-plan.md` (PR 2), raport
`docs/dl-review-v2-completion-report.md`. DL decydował o wysyłce bez wymagań klienta obok, bez marży i bez
porównania z innymi osobami; „Wróć do poprawy” niosło jedno zdanie, więc rekruter zgadywał, co poprawić.

- **Prośba o poprawki (D6) to wiersz `screening_form_versions` z `action="fix_requested"`** i `meta = {stage_id,
  fields: [{key, label}]}` — nie nowa kolumna (`services/screening_fix_requests.py`). Klucze: `question:<id>`,
  `field:<pole karty>`, `field:overall_fit`, `candidate_rate`, `cv`. Lista jedzie z ruchem
  (`StageMove.fix_fields`, najwyżej 30) i wolno ją wysłać WYŁĄCZNIE przy ruchu z kolumny „QC CV” na
  „Zweryfikowany” poza Nordeą (422 `FIX_FIELDS_NOT_ALLOWED`; nieznany klucz = 422 `FIX_FIELDS_INVALID`). Prośba
  jest otwarta, dopóki najnowszy wiersz etapu pary to `meta.stage_id`; „poprawione” liczy porównanie migawki
  z wersją prośby (CV — `branded_updated_at` późniejsze niż prośba, z pominięciem szkicu podpiętego przez
  automat auto-CV po ruchu na „Zweryfikowany”: `cv_changed_by_person`). Zapis prośby podbija wersję formularza, więc
  otwarty u rekrutera formularz dostaje 409 i wczytuje się z zachowaniem jego zmian.
- **Rekruter widzi prośbę w formularzu screeningu** (`GET /api/screening-form` → `fix_request`,
  `handback_stage_def_id`): baner „Delivery Lead prosi o poprawki (N)”, pola podświetlone („do poprawy” /
  „poprawione”) i „Zapisz i oddaj do przeglądu DL” (zapis, potem ruch na etap QC CV). Dzwonek zwrotu
  i „Twoje CV w drodze” (`fix_labels`) wymieniają pola; link dzwonka otwiera panel na screeningu.
- **Kontekst przeglądu (D9): `GET /api/dl-review/context?candidate_id&job_id`** (`api/dl_review.py`,
  `services/dl_review.py`; bramka: uprawnienie `recruitment_manage` + odczyt rekrutacji). Wymagania z
  `dz_review.job_requirements` + krytyczne + doświadczenie Championa, status `met|missing|unknown` z dowodem
  (profil, CV, notatka, rozmowa) — zdanie i branża to „do oceny”, nigdy „brak”. Do tego ocena rekrutera, ryzyka
  (weto, deal-breaker, QC, ponad budżet, praca u innego klienta, wcześniejsze wysyłki do tego klienta), budżet,
  punkty odniesienia (stawki konsultantów u klienta z `services/client_consultant_rates.py` — mediany bez nazwisk,
  ostatni kontrakt osoby) i lista pól do poprawy. **Kwoty klienta tylko przy `can_read_client_finance`** dla
  klienta rekrutacji, **stawki do klienta tylko przy `user_can_view_client_rate`** — inaczej pola są `null`, nie
  zera. Stawka do klienta we wcześniejszej wysyłce do INNEGO klienta — tylko z wglądem w kwoty tamtego klienta
  (`Access.client_rate_for`, DL spoza portfela jej nie widzi). Agregaty konsultantów liczą wyłącznie klientów
  z wglądem w kwoty, a mediana i zakres dopiero od 3 osób (`MIN_AGGREGATE_SIZE` — przy 1–2 zdradzałyby stawkę
  konkretnej osoby). Osoba bez wiersza etapu w rekrutacji = 404. Podpowiedź stawki do klienta: ta para, potem
  ostatnia wysyłka tej osoby do tego klienta.
- **Marżę liczy przeglądarka** (`lib/dl-review-margin.ts`): stawka do klienta − stawka kandydata po przeliczeniu
  na zł/h (dzień ÷ 8, miesiąc ÷ 168), miesięcznie × 168; waluta inna niż PLN albo brak stawki kandydata = „nie do
  porównania”, nigdy zero. Ostrzeżenie przy marży poniżej mediany klienta.
- **Układ (od 09.10.2026, D4):** CV jest pierwsze i największe. Tryb liczy się z szerokości kontenera przeglądu
  (`useElementWidth`): poniżej 1100 px jedna kolumna; 1100–1639 px CV + decyzja 460 px, a „Wymagania i ocena” są
  zakładką w polu CV (w decyzji pasek „Wymagania N/M · brak: …” z „Pokaż”); od 1640 px CV + wymagania 440 px +
  decyzja 520 px. Przyciski decyzji stoją w przyklejonej stopce. Na Tablicy przegląd ma własny rozmiar panelu
  `review` (całe okno, zakrywa menu), na pulpicie okno do 2000 px. Podgląd oryginału (pdf.js, docx-preview) idzie
  za `next/dynamic`.
- **Porównanie (D10): `GET /api/dl-review/jobs/{job_id}/queue`** — osoby w kolumnie „QC CV” rekrutacji (stała
  liczba zapytań, najwyżej 50, najdłużej czekające), u Nordei pusta lista z `cpro_client: true`. Wejścia:
  „Porównaj (N)” przy grupie rekrutacji w „Czeka na Twój przegląd” i w nagłówku kolumny „QC CV” na Tablicy (DL,
  2+ osoby, poza Nordeą). Wiersz niesie wiersz kolejki pulpitu, więc „Przejrzyj” nie robi drugiego żądania.
- Harness `/preview/dl-review` (`?state=queue`, `?state=returned`, `?as=recruiter`). Wzmianki w sekcjach 0352
  i 0413 o przeglądzie bez marży i o „Wróć do poprawy” z samą uwagą opisują stan sprzed 08.10.2026.
