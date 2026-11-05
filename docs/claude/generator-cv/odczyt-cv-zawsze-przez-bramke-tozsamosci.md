# Odczyt CV zawsze przez bramkę tożsamości

Każda ścieżka, która czyta CV modelem i zapisuje wynik w profilu, woła najpierw
`record_detected_identity`. Bieg masowy `cv_field_backfill` (Fala 3, 08.2026) tego
nie robił: profile dostały umiejętności, miasto i lata z tekstu pliku, w którym
model przeczytał inne imię i nazwisko, a kwarantanna nie miała o tym wiersza.

- Tekst bez dokumentu źródłowego idzie jako `legacy_cv`. Klucz `cv_storage_key`
  prawie nigdy nie wskazuje wiersza `candidate_documents`, więc dokumentu nie da
  się po nim znaleźć (pomiar 05.11.2026: 2 z 408 plików).
- Bieg masowy przy sprzeczności nazw nie wpisuje faktów i niczego nie kasuje
  (decyzja Artura 05.11.2026). Profil dostaje wiersz `inconclusive` ze znacznikiem
  `mismatch_held_for_review`, a jego id trafia do `identity_mismatch_ids` w
  statystykach biegu. Pomiar 05.11.2026 na 133 sprzecznościach: 64 własne CV, 46
  cudzych, a 23 własnych nie da się odróżnić po nazwie (fałszywa nazwa w profilu,
  pseudonim). Tekst cudzego CV zostaje do przeglądu przez człowieka. Pozostałe
  ścieżki (wgranie, poczta) dalej dają kwarantannę, bo dotyczą jednego pliku.
- `evaluate_identity_match` nie potwierdza innej osoby, gdy obie tożsamości mają
  wspólne słowo albo jedna część nazwy jest prawie równa (podobieństwo od 0,8).
  Traffit dzielił nazwę po pierwszej spacji, a model po sensie, więc bez tego
  własne CV osoby z dwoma imionami wyglądało jak cudze: na 608 sprzeczności 415
  to była ta sama nazwa w innej formie.
- Tak samo przy podobnym brzmieniu (`similar_name_sound`), tych samych literach w
  innym podziale (`same_letters_other_split`) i numerze z profilu spoza odczytu
  (`profile_phone_other_form`). Ta sama osoba bywa zapisana po polsku, rosyjsku i
  białorusku bez wspólnego słowa. Trzy sygnały zdjęły 41 z 64 własnych CV i 1 z 46
  cudzych (to samo nazwisko w rodzinie).
- Telefon dowodzi tylko w innym zapisie niż ten odczyt i zapisany odczyt profilu:
  te same cyfry, inne znaki. `_apply_cv_contact_fields` zapisuje numer surowo, więc
  równy zapis mógł przyjść z tego samego pliku. E-mail nie ma takiego sygnału, bo
  zapis idzie małymi literami. Nazwa pliku też nie: zawierała nazwisko profilu w 7
  cudzych przypadkach.
- Wiersz `confirmed_mismatch` zostaje, także gdy nowa reguła oceniłaby plik inaczej.
  Stare decyzje zmienia tylko człowiek (`override_identity_quarantine`).
