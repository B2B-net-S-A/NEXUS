# Umowa i NDA nie są źródłem CV w generatorze (25.11.2026)
<!-- indeks: `cv_source.looks_like_contract_file` / `contract_file_clause`, filtr `_supported_cv_doc_filter`, komunikat `no_cv_file`, wspólny wzorzec z `app.cli.contract_as_cv_repair` -->

Decyzja Artura z 25.11.2026 (wariant „blokada”, nie ostrzeżenie ani uwaga w QC).

## Skąd

Generator CV bierze każdy PDF/DOCX z profilu (`_supported_cv_doc_filter`).
Rodzaj „other” go nie wyklucza, a import Traffita oznaczał umowę albo NDA jako
„CV”, często jako główne (`kandydaci-wyszukiwanie/umowa-jako-glowne-cv-naprawa.md`).
Z takiego pliku powstawało CV z samych notatek, bez dat ról.

Pomiar na kopii produkcji 25.11.2026 (1727 CV z 60 dni z plikiem dopasowanym
po `editorial_provenance.cv_sha256`): 3 CV z umowy przedwstępnej albo NDA
(jedno ręcznie, dwa z automatu; NDA to skan bez tekstu, więc treść pliku
niczego by nie wykazała). 140 z 66 455 osób miało umowę albo NDA jako pierwszy
plik do CV (138 jako główne CV), 9 nie miało innego pliku.

## Reguła

- Plik z umową albo NDA w nazwie, bez CV w nazwie, nie jest źródłem CV:
  nie ma go na liście plików generatora (`/cv-sources`, karta „CV do
  klienta”), nie wybiera go wybór domyślny ani automat.
- Osoba z samą umową: automat pomija z powodem `no_cv_document`, ręcznie
  komunikat „W profilu jest umowa albo NDA, a nie CV kandydata. Wgraj CV.”
- Umowa wskazana wprost (`cv_document_id`): „Ten plik to umowa albo NDA, nie CV.”
- Rozpoznanie po nazwie, nie po treści, bo umowy to często skany.

## Wzorzec nazwy

`cv_source._CONTRACT_WORDS` (Python i Postgres `~*` dają to samo; sprawdzone na
118 145 nazwach z kopii produkcji, 703 trafienia, 0 różnic):

- „umow”/„umów” tylko na początku słowa: nazwiska z „umow” w środku (np. fikcyjny Fikumowski)
  i „podsumowanie” zostają CV;
- „contract”, ale nie „contractor” (opis kandydata); „Contract Manager” to stanowisko;
- „agreement”, „NDA” jako osobne słowo, „non-disclosure”;
- CV, resume albo curriculum w nazwie zawsze wygrywa.

Ten sam wzorzec bierze `app.cli.contract_as_cv_repair`. Stary
(„umow|umów|contract|agreement”) w próbie na sucho 25.11 zdjąłby 5 prawdziwych
CV (nazwiska, „podsumowanie”, „contractor”) i pomijał 9 osób z NDA.

## Czego to nie robi

- Nie zmienia profilu: umowa zostaje głównym CV, dopóki nie przejdzie naprawa
  z `umowa-jako-glowne-cv-naprawa.md`.
- Nie zmienia „Oryginału CV” ani `get_current_cv`.

Testy: `backend/tests/test_cv_source_contract_file.py`,
`backend/tests/test_contract_as_cv_repair.py`.
