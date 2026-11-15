# Katalog raportów klienta (0709, 15.11.2026)
<!-- indeks: raport klienta = wiersz danych, nie kod; rejestr generatorów; zatwierdza DL klienta (zgodność: admin); DL wysyła sam, NEXUS zapisuje; kalendarz z definicji × okresów; „Znajdź w umowach” to propozycja; bez listy id klientów w kodzie -->

Każdy klient wymaga innych raportów: karty czasu i protokoły do faktury,
zestawienia zaangażowania, kwartalne zestawienia zleceń, roczne statystyki
i raporty realizacji umowy, raporty dla spotkań zarządczych. Inwentarz
z umów 35 klientów i makiety: prywatny artefakt z 15.11.2026 (link w pamięci
sesji, nie w repo — ma nazwy i liczby). Decyzje Artura z 15.11.2026 niżej.

- **Raport to wiersz danych przy kliencie** (`client_report_definitions`):
  skąd wymóg (umowa lub aneks z numerem fragmentu i paragrafem albo Delivery
  Lead), rodzina, rytm, reguła terminu (`services/client_reports/schedule.py`),
  odbiorca, kanał, kto przygotowuje, generator i jego `params`. Nie dokładaj
  listy id klientów w kodzie ani `if client == …` w generatorze: tak zaczął
  raport BNP (`frozenset({12})`, #3265) i od 0709 jego przycisk w Projektach
  bierze dostępność z katalogu (zasiew definicji dla dotychczasowego klienta).
- **Generator jest wspólny** (`services/client_reports/registry.py`, moduły
  w `generators/`): klucz, rytmy, czy plik ma kwoty (`needs_amounts` →
  „Stawki i kwoty: podgląd”) albo stawki do klienta (`needs_client_rate`),
  pola parametrów. Nowy klient z takim samym raportem = nowy wiersz, bez kodu.
  Kalkulator marży per konsultant (Nordea) robi osobny moduł — katalog go
  nie liczy.
- **Rozliczenia zostają w Rozliczeniach.** Karta czasu, KEŚU, timesheet
  i protokół jako podstawa faktury to rodzina „rozliczenie”: katalog pokazuje
  termin i prowadzi do `/finance?view=settlements`, nie liczy drugi raz.
- **Zatwierdza DL klienta, admin zawsze** (`catalog.can_confirm`). Rodzina
  „zgodność” (sprawozdania finansowe, ciągłość działania, incydenty,
  podwykonawcy, RODO) — tylko admin, bo to obowiązki spółki. Wpis osoby bez
  prawa zatwierdzenia i każda propozycja z umów czekają jako `proposal`;
  odrzucona nie wraca przy kolejnym „Znajdź w umowach”.
- **„Znajdź w umowach” to propozycja, nie obowiązek.** Kod wybiera fragmenty
  umowy i aneksów ze słowami o raportach, model `client_report_requirements`
  (F49, rejestr `ai_models.py`) wypisuje obowiązki z numerem fragmentu, parser
  odrzuca wpis z fragmentem spoza listy. Bez modelu DL dostaje wycinki
  i wpisuje raport sam. Trasa ma bramkę umów (`LegalDocsReader`), bo wycinki
  to treść umowy.
- **DL wysyła raport sam**, ze swojej poczty; NEXUS zapisuje wysyłkę
  („Oznacz jako wysłany”: data, adresat, plik) w `client_report_runs`. Pobranie
  zapisuje kopię pliku jako „wygenerowany”. Automatycznej wysyłki do klienta
  nie ma — plik idzie do banku, więc człowiek go ogląda.
- **Kalendarz liczy się przy odczycie** (definicja × okresy, stan z historii).
  Terminów sprzed „obowiązuje od” albo dnia dodania raportu nie pokazujemy
  jako zaległych (`catalog.tracking_start`) — inaczej świeży katalog świeci
  się na czerwono za miesiące, w których nikt go nie prowadził.
- **Wejścia:** tryb „Raporty dla klientów” w module Klienci
  (`/clients?view=reports`, DL domyślnie „Moje”) i zakładka „Raporty” w karcie
  klienta pod „Więcej”. Bez nowej pozycji menu.
- **Bramki:** router za sekcją Delivery; odczyt „podgląd Delivery”, zapis
  „edycja klientów”, zakres klientów DL-a w handlerze; pobranie plików z
  `NOT_READ_ONLY`. Plik spoza NEXUSA w historii pobiera tylko osoba z podglądem
  kwot (sprawozdania i protokoły bywają z kwotami, jak umowy).
- Repo publiczne: definicji klientów nie zasiewamy z inwentarza (to treść
  umów). Katalog wypełnia DL przyciskiem albo ręcznie.
