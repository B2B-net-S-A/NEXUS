# Sprzęt i protokoły recepcji (D2–D10, 16.10.2026)

Ewidencja sprzętu, kart SIM i kart dostępu oraz protokoły zdawczo-odbiorcze
przeszły z Exceli i Worda recepcji do NEXUSA (D1 = tylko NEXUS, uprawnienie
„Sprzęt” osobno od Kadr). Ekran `/equipment`, zakładka „Sprzęt” przy kontrakcie,
osobie z kartoteki i uczestniku Akademii.

## Czego nie przechowujemy (D10)

- Rejestr nie ma kolumn na klucz BitLocker, PUK, PIN, PESEL ani prywatny e-mail.
  Import plików recepcji odrzuca je dwa razy: po nagłówku kolumny (kolumna nie
  jest czytana) i po wzorcu wartości w czytanych kolumnach
  (`app/services/equipment/sanitize.py`). Nowa kolumna w imporcie albo w formularzu
  egzemplarza = sprawdź, czy nie otwiera drogi dla tych danych.
- Plik importu nie jest przechowywany — partia ma jego SHA-256 i oczyszczone wiersze.

## Rejestr i posiadacze

- Jedna pozycja = jeden fizyczny egzemplarz. Numery ewidencyjny, S/N, IMEI, ICCID,
  numer telefonu SIM i numer karty dostępu unikalne, gdy niepuste.
- „Wolny” = stan `na_stanie` i brak aktywnego wydania. Najwyżej jedno aktywne
  wydanie na egzemplarz pilnuje indeks częściowy (także wyścig dwóch wydań).
- Posiadacz to dokładnie jeden z czterech: konto NEXUSA, kontrakt, osoba
  zewnętrzna bez konta, uczestnik edycji Akademii (`academy_application_id`, 0461).
  CHECK `num_nonnulls(…) = 1` w bazie.
- Cennik per model (D5); wartość pozycji pochodzi z cennika, zmiana przy wydaniu
  dotyczy tylko tego protokołu. Karta SIM i karta dostępu są w protokole bez
  wartości (D6). Własność (`nasz` / `klienta`) przechodzi do zakładki kontraktu.
- Twarde skasowanie kontraktu kasuje kaskadą jego wydania — wyzwalacz zwraca
  egzemplarz na stan. Zakładka „Sprzęt” kontraktu (`contract_equipment`) wskazuje
  egzemplarz z rejestru (`item_id`, `assignment_id`).

## Wydanie, zwrot, protokół

- Wydanie i zwrot to jedna transakcja: egzemplarze `FOR UPDATE`, statusy,
  wydania, protokół i — dla konsultanta — pozycje zakładki kontraktu powstają
  razem albo wcale. Stan przy zwrocie decyduje o stanie egzemplarza
  (uszkodzony → serwis, zgubiony → zgubiony).
- Protokół z wzoru recepcji 1:1 (`protocol_template.py`, tabela pozycji, kwota
  słownie `pln_words_with_fraction`), numer `PZO/<rok>/<miesiąc>/<kolejny w roku>`
  pod blokadą doradczą, migawka posiadacza i pozycji zamrożona w chwili wydania.
- Podpis (D4): link dla osoby, papier albo profil zaufany (skan wgrywa recepcja).
  Stan „podpisany” potwierdza CZŁOWIEK — automatyczna weryfikacja podpisu
  zaufanego bywa „nieokreślona”.
- Link (D8): publiczna strona `/protocol/<token>`, trasa
  `/api/public/equipment-protocols/{token}` z limiterem (moduł bez
  `from __future__ import annotations`). Token tylko w adresie, w bazie SHA-256;
  14 dni, jednorazowy; nowy link unieważnia poprzednie. Zły, zużyty, wygasły
  i unieważniony token wyglądają z zewnątrz tak samo.

## Zadania recepcji („Do zrobienia”)

- Zakłada je NEXUS: start kontraktu u klienta, który bierze sprzęt od nas
  (`clients.equipment_provider = 'nasz'`, 7 dni roboczych wcześniej, D7), koniec
  współpracy, wejście i odejście pracownika, niepodpisany protokół, podpisana
  umowa i rezygnacja uczestnika Akademii. `source_key` unikalny — drugie wołanie
  nie dubluje, otwarte zadanie dostaje tylko nowy termin.
- Haki kontraktu (`app/services/hr/contract_hooks.py`) biegną w savepoincie:
  awaria sprzętu nie blokuje zmiany kontraktu. Źródłem prawdy jest przegląd
  `reconcile_upcoming` w pętli HR (kontrakt zmienia stan wieloma ścieżkami).

## Import plików recepcji

- Wgranie → partia z decyzjami (`przyjmij`, `pomin`, `konflikt`, `do_wyjasnienia`)
  → arkusz kontrolny XLSX dla recepcji → poprawki → zatwierdzenie. Nic nie trafia
  do rejestru przed zatwierdzeniem. Laptopów bez stanu nie zgadujemy — idą do
  „Do wyjaśnienia”.

## Intune (etap 4, D9) i edycje Akademii (etap 5)

- Intune: wyłącznie odczyt (`DeviceManagementManagedDevices.Read.All`, zgoda
  administratora przy przełączeniu), migawka w `equipment_intune_devices`,
  rozjazdy z ewidencją liczone przy odczycie, recepcja je wyjaśnia albo pomija.
  Bez kluczy odzyskiwania i danych spoza urządzenia.
- Edycja Akademii: check lista recepcji per edycja (`academy_session_checklist`),
  hotel i bilet uczestnika (`academy_participant_logistics`), zestaw i protokół
  z wydań sprzętu. Rezygnacja zamienia „zrobione” hotel i bilet na
  „do anulowania” i zakłada zwrot, jeśli uczestnik ma rzeczy.
