# Odczyt CV zawsze przez bramkę tożsamości

Każda ścieżka, która czyta CV modelem i zapisuje wynik w profilu, woła najpierw
`record_detected_identity`. Bieg masowy `cv_field_backfill` (Fala 3, 08.2026) tego
nie robił: profile dostały umiejętności, miasto i lata z tekstu pliku, w którym
model przeczytał inne imię i nazwisko, a kwarantanna nie miała o tym wiersza.

- Tekst bez dokumentu źródłowego idzie jako `legacy_cv`. Klucz `cv_storage_key`
  prawie nigdy nie wskazuje wiersza `candidate_documents`, więc dokumentu nie da
  się po nim znaleźć (pomiar 05.11.2026: 2 z 408 plików).
- Decyzja `confirmed_mismatch` w biegu masowym usuwa z profilu tekst CV i przelicza
  wektor. `cv_text_backfill` nie odtwarza tekstu z pliku w kwarantannie, bo
  czyszczenie zostawia `cv_storage_key`.
- `evaluate_identity_match` nie potwierdza innej osoby, gdy obie tożsamości mają
  wspólne słowo albo jedna część nazwy jest prawie równa (podobieństwo od 0,8).
  Traffit dzielił nazwę po pierwszej spacji, a model po sensie, więc bez tego
  własne CV osoby z dwoma imionami wyglądało jak cudze: na 608 sprzeczności 415
  to była ta sama nazwa w innej formie.
- Wiersz `confirmed_mismatch` zostaje, także gdy nowa reguła oceniłaby plik inaczej.
  Stare decyzje zmienia tylko człowiek (`override_identity_quarantine`).
