# Prolongata to wybór człowieka, nie uwaga z importu (19.11.2026)

<!-- indeks: `prolongation_status`, `ProlongationSelect`, `ContractRegisterDialog`, import kontraktów z Excela, `pko_prolongation_import_repair` -->

- `prolongation_status` (Tak / Nie / Negocjacje / Nieznany) to prognoza
  przedłużenia, którą wpisuje osoba: wybór w wierszu (`ProlongationSelect`) albo
  okno pól rejestru (`ContractRegisterDialog`). Każdy taki zapis zostawia
  w historii kontraktu wpis `updated` z kluczem `prolongation_status`.
- Import i automaty zostawiają `unknown`. Uwaga z arkusza (np. „brak nowego
  zamówienia”) idzie do notatki kontraktu, nie do prognozy. 26.06.2026 skrypt
  importu z Excela „Zamówienia_PKO BP” zapisał tę uwagę jako „Nie” w 14
  kontraktach PKO BP. 19.11 zakładka Klient › Konsultanci pokazała to jak
  decyzję o odejściu 12 osób, które miały już zamówienia na IV kwartał. Korekta:
  `app/services/pko_prolongation_import_repair.py` (znacznik
  `pko_prolongation_import_reset_2026_11_19`).
- Koniec zamówienia to nie odejście. PKO BP wystawia zamówienia kwartalne, więc
  prawie wszystkie kończą się z końcem kwartału (30.09.2026: 16, 31.12.2026: 30).
- Wartości inne niż `unknown` są rzadkie (19.11.2026: 32 z 588 kontraktów,
  ostatni zapis 21.08.2026), a nowe zamówienie ich nie zmienia.
