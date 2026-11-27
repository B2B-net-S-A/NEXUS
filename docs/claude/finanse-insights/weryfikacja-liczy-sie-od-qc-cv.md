# Weryfikacja liczy się od wejścia na „QC CV” (0797, 27.11.2026)

Decyzja Artura z 27.11.2026: w statach, celach („Weryfikacje · N / 4 dziś”),
Lidze, Insights i precyzji weryfikacja to **pierwsze wejście pary na kolumnę
QC CV albo dowolną dalszą** (CV wysłane, Rozmowa u klienta, Akceptacja
i umowa, Zatrudniony), które nastąpiło po zaakceptowanej weryfikacji. Data
weryfikacji = dzień tego wejścia. Para, która stoi w „Zweryfikowanym” albo
z niego odpadła, nie ma weryfikacji. Cel 4 dziennie zostaje (decyzja z tego
samego dnia).

Dlaczego: do 27.11 liczyło się samo przesunięcie na „Zweryfikowany”, także
dla par, które nigdy nie dostały CV firmowego. Listopad 1–26 na produkcji:
1031 weryfikacji, z czego 923 doszły do QC CV (−10%).

Jak to jest zrobione — nie cofaj „przy okazji”:

- **Kamień `verified` w `analytics_first_milestones`** ma datę wejścia na
  QC CV, ale autora i `candidate_stage_id` z wiersza weryfikacji. Wszyscy
  konsumenci widoku (ok. 60 plików) dostają nową definicję bez zmian w kodzie.
- **`VERIFIER_ANCHORED_CTE`** (`kpi_panel.py`): liczony wiersz weryfikacji
  idzie z `classified_qc`, a **kotwica zasługi** (`classified_verified`,
  `pair_first_verifier`) zostaje na samej weryfikacji. Dzięki temu
  rekomendacje, rozmowy i placementy dostaje ta sama osoba co przed zmianą
  (sprawdzone na kopii produkcji: pozostałe etapy bez zmian co do sztuki).
  `pair_first_verifier` czyta `candidate_stages`, nie widok — widok ma już
  datę QC.
- **Kolumnę QC CV poznaje się po nazwie etapu**, nie po kodzie: „QC CV”
  i „Przepuszczony przez DZ” mają kod `interview`, „Wysłać do Cpro” (Nordea)
  kod `new`. Część reguły zależna od nazwy to kolumna generowana
  `pipeline_stage_defs.board_reach` (funkcja `stage_def_board_reach`), reszta
  to `reaches_cv_qc_sql` w `services/verification_milestone.py`. Razem są
  lustrem `board_column_for`; pilnuje `tests/test_verification_from_qc_cv_db.py`
  na `board-stage-cases.json`. Nowa nazwa etapu w kolumnie QC CV = przypadek
  w tym pliku.
- Regexu po nazwie etapu nie wstawiaj do widoku dla każdego ruchu: widok był
  przez to 40× wolniejszy (1,16 s zamiast 0,03 s na kopii produkcji). Kolumna
  generowana + złączenie zbiorowe dają 0,1 s.
- Dni sprzed 12.10.2026 (DynaReporter) liczą się po staremu — w trendzie
  rok do roku widać skok w miejscu zmiany.
