# Premie z automatu: nikt nie wpisuje i nie usuwa premii z palca (09.11.2026)
<!-- indeks: auto_assign_from włącza samo przyznawanie, ręcznie tylko admin z powodem, Zgłoś, wstrzymane HOLD_FLAGS, 200% czeka na wynik, odbiorca odszedł, pozycje poza regułami rule_items -->

Decyzja Artura z 09.11.2026: premie liczy i przyznaje automat. Jak coś się nie
zgadza, admin zmienia zasadę albo dane, a automat przelicza. Powód: w październiku
Płace usunęły ręcznie 33 premie i wpisały 17.
Kod: `services/hr/bonus_auto_assign.py`, `_manual_gate` w `api/hr_payroll.py`.

- **Włącznik:** `hr_bonus_rules.auto_assign_from` (`RRRR-MM`, Ustawienia → Rozliczenia →
  Premie). Puste = dawne zachowanie. Włącza też dopasowanie premii z importu do gwarancji.
- **Co się przyznaje:** w nocnym przebiegu i przy „Przelicz propozycje teraz” propozycje
  z placementów i Ligi od tego miesiąca premii, po terminie. `assigned_by` puste, osoba
  dostaje dzwonek.
- **Co czeka:** zamknięty miesiąc; kontrakt podpisany w miesiącu programu 200% bez
  zapisanego wyniku; znacznik z `HOLD_FLAGS` (stawka, brak zamówienia, inna osoba,
  druga rekrutacja, druga premia). Wtedy admin zmienia zasadę albo dane.
  Wstrzymana propozycja blokuje zamknięcie miesiąca, więc admin rozstrzyga ją przed nim.
  Premia 200% przyznaje się bez czekania na termin, bo należy się w miesiącu podpisu.
- **Odbiorca odszedł** (konto nieaktywne, premia jeszcze nieprzyznana): premia przepada,
  także DL-owi i w Lidze, powód `recipient_left`, i nikomu nie przechodzi. Powrót konta ją przywraca.
- **Ręczne akcje** (dodanie, zmiana, zatwierdzenie, usunięcie, zwrot z gwarancji i jego
  zdjęcie, arkusz, zapis reguł): tylko admin, zmiana i usunięcie z powodem. Reszta dostaje
  403. Stan dla ekranów: `GET /api/hr/payroll/bonus-mode`.
- **Zgody na premię** poza umową (`/api/hr/approvals`) po włączeniu zatwierdza tylko admin.
- **Płace i koordynatorzy** widzą listę i „Zgłoś adminowi”
  (`POST /api/hr/payroll/bonuses/{id}/report`, dzwonek do adminów). Fakty o kontrakcie
  (data podpisu, koniec, stawka) poprawiają dalej, premia przelicza się sama.
- **Pozycje poza regułami** (`rule_items`: osoba, kwota, miesiąc, powód): premia bez
  reguły, np. za punkty. Automat przyznaje każdą raz (klucz z treści pozycji w migawce),
  więc zmiana treści tworzy nową pozycję.
