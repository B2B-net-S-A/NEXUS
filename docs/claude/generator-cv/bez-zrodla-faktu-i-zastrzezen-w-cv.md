# Bez źródła faktu i zastrzeżeń „niekomercyjnie” w CV (17.11.2026)

<!-- indeks: `strip_source_mentions`, `_SOURCE_NOTE_RE`, „potwierdzone podczas screeningu”, „per screening notes”, „według notatek”, „(niekomercyjnie)”, kategoria łączona -->

Zgłoszenie Artura 17.11.2026: „Bazy danych (niekomercyjnie): MongoDB - znajomość
potwierdzona podczas screeningu, bez doświadczenia komercyjnego”. Decyzja: generator
nigdy nie pisze, skąd ma fakt, i nie dopisuje „niekomercyjnie” / „bez doświadczenia
komercyjnego” — ani przy pozycji, ani w nazwie kategorii, ani w innych sekcjach.
Klient nie ma wiedzieć, skąd wzięliśmy fakt, a zastrzeżenie czyta jako „nie umie”.

Kopia produkcji z 16.11 (958 CV z 30 dni), oprócz zgłoszonego przypadku: zadania
„(per screening notes)” i „; screening notes additionally report…”, język
„Angielski - B2 według notatek ze screeningu; C1 według CV”, punkt „Dlaczego”
„…; ma także niekomercyjne doświadczenie z GraphQL”, umiejętność „GraphQL
(doświadczenie niekomercyjne)”.

- **Prompt** (`legacy_v7/prompts.py`, sekcja notatek ze screeningu, PL i EN): reguła
  „ŹRÓDŁO FAKTU NIE TRAFIA DO CV”. Przy różnym poziomie języka w CV i w notatkach
  jeden poziom — ten z rozmowy.
- **Kod** (`_helpers.strip_source_mentions`, w pipeline zaraz po
  `strip_unsupported_terms`): nawias z wtrąceniem znika, zdanie kończy się na ostatnim
  średniku/przecinku/myślniku przed wtrąceniem, język zostaje z pierwszym poziomem.
  Kategoria „Bazy danych (niekomercyjnie)” łączy się z „Bazy danych” (pozycje na
  końcu). Rekruter dostaje uwagę WERYFIKUJ z tym, co zniknęło.
- **Wzorzec jest wąski** (`_SOURCE_NOTE_RE`): samo „screening” (AML: „sanctions
  screening”), „deklaracje podatkowe” i „participated in recruitment interviews” to
  fakty i zostają. Na 958 CV filtr zmienia 4 dokumenty, wszystkie z prawdziwym
  dopiskiem.
- Uzupełnia #3542 (dopiski poziomu przy umiejętnościach, `_without_level_note`).
  Ścieżka v10 bez zmian; CV wygenerowane wcześniej nie zmieniają się same.

Testy: `backend/tests/test_cv_no_source_mentions.py`.
