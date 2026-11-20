# Ręczny aneks bez zmiany nie powstaje (decyzja Artura 19.11.2026)
<!-- indeks: duplikat aneksu 409, aneks bez zmiany i „przedłużenie” skracające umowę 422, tylko okno „Dodaj aneks”, sprzątanie historii 19.11 -->

Odczyt produkcji 19.11.2026: wśród 130 aneksów kontraktów trzy kontrakty miały
po 2–3 identyczne aneksy (#116, #155, #444). W #398 pomyłkę wpisu poprawiano
kolejnymi aneksami, w tym „przedłużeniem”, które skracało koniec umowy. Wszystkie
powstały ręcznie w oknie „Dodaj aneks” przy wprowadzaniu wstecz 29.06–10.07.2026.
Aneksu nie da się poprawić ani usunąć w aplikacji. Kwot to nie zmieniało, bo
identyczne kroki harmonogramu dają tę samą stawkę, ale zakładka „Aneksy” myliła.

- **Reguła działa tylko przy ręcznym zapisie** (`POST /api/contracts/{id}/amendments`,
  `reject_redundant=True` w `apply_contract_amendment`, logika w
  `services/contract_amendment_guard.py`). Podpis aneksu w Generatorze
  (`b2b_documents/effects.py`) i wpis stawki z dokumentu
  (`contract_rate_documents`) idą bez niej. Podpisany dokument ma swój skutek,
  a automat sam porównuje stawkę z harmonogramem. Nie przenoś sprawdzenia do
  wspólnej ścieżki, bo wywróciłoby „Oznacz jako podpisany”.
- **409 `amendment_duplicate`** dostaje powtórzenie ostatniego aneksu tego samego
  typu i dnia wejścia z tą samą treścią. Odpowiedź niesie `amendment_id`.
  Powrót do wartości, które później tego samego dnia nadpisał inny aneks, nie jest
  duplikatem.
- **422 `amendment_no_change`** dostaje aneks, w którym każde podane pole ma już
  tę wartość. Stawkę porównujemy z harmonogramem w dniu kroku
  (`_amendment_step_from`), a nie ze zrzutem `old_values`. Zrzut trzyma stawkę
  „na dziś”, więc przesunięcie dnia wejścia tej samej stawki wyglądało w nim na
  „X → X”, choć zmieniało stawkę na kilka dni (aneks 48 w #398). Taki aneks
  przechodzi.
- **422 `extension_shortens`** dostaje „przedłużenie” na datę wcześniejszą niż
  obecny koniec umowy. Wcześniejszy koniec zapisuje okno „Zakończ współpracę”
  (`zakonczenie-wspolpracy-okno-rozwiazanie-umowy.md`). Przedłużenie umowy bez
  daty końca rozstrzygają dotychczasowe reguły (B2B:
  `umowa-b2b-jest-bezterminowa-dopoki-ktos-jej-recznie.md`).
- Komunikaty idą w `detail.message`, więc okno pokazuje je przez `apiErrorMessage`
  bez zmian na froncie. Nie dokładaj „Zapisz mimo to”: Artur wybrał blokadę
  zamiast ostrzeżenia.
- **Sprzątanie 19.11.2026:** naprawa `contract_amendment_history_repair.py` (blok
  `repair-contract-amendment-history-2026-11` w `entrypoint.sh`, znacznik
  `contract_amendment_history_cleanup_2026_11_19`) usuwa aneksy 3, 29 (#155), 31
  (#116), 20 (#444), 47 i 48 (#398) oraz identyczne kroki stawki. Usunięte wiersze
  w całości leżą pod `repair_details_contract_amendment_history_2026_11_19`, poza
  publicznym workflow paragonów.
- Testy: `tests/test_contract_amendment_guard.py`,
  `tests/test_contract_amendment_history_repair.py`.
