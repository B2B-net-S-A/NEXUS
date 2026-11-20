# Opieka przy back office: Delivery Lead bez podopiecznych z automatu, zdrowie bez rytmu
<!-- indeks: effective_owners bez DL-a przy back_office, back_office_on, karty rozmów i decyzji tylko z opiekunem, opinia menedżera prowadzi DL klienta, zdrowie bez reguł rytmu (HealthSignals.rhythm), „Moi podopieczni” i „Moi” tylko z podopiecznymi, Konsultanci bez rytmu, karta konsultanta i panel tablicy bez rytmu (planItemOverdue, nearestPlanItem), 20.11.2026 -->

Decyzje Artura z 20.11.2026 (przegląd z zrzutami i wariantami:
https://claude.ai/artifact/2PRniukBqfxb4u6YcQaVso, wybrany wariant A i „zdrowie bez
reguł rytmu”). Uzupełnia `back-office-jeden-zespol.md` i ma pierwszeństwo przed zdaniem
o łańcuchu opiekuna w `opieka-mapa-technologii-i-sprawy.md`, gdy moduł `back_office`
jest włączony.

Powód: 468 z 512 aktywnych kontraktów nie miało wpisanego opiekuna, więc opiekunem
z łańcucha był DL klienta. 7 DL-i miało 740 kart „Moje” (DL 27: 391), od startu Opieki
nikt nie zapisał żadnej rozmowy ani opinii, a 73 dzwonki „Kontakt z konsultantami”
od 19.10 miały 0 odczytów. DL-e nie pracują w back office'ie (Artur 19.11), a to, co
dotyczy konsultanta, kolejka ma u siebie („Kontakt 7. dnia”, „Co dalej po projekcie”,
„Przedłużenie”). Koniec zamówienia DL widzi w panelu „Moi klienci” i dzwonkach 30/14/7 dni.

## Opiekun kontraktu

- Z modułem `back_office` łańcuch (`care/access.py`, `effective_owners`) kończy się na
  polu kontraktu i domyślnym opiekunie klienta. Ogniwa DL-a (prowadzący rekrutację,
  główny DL klienta) nie ma, więc DL nie jest opiekunem z automatu. Wyłączenie modułu
  przywraca dawny łańcuch bez zmian w danych.
- Za łańcuchem idą: tablica, „Konsultanci” (`is_mine`), dzienne przypomnienia
  (`care_contact_due` — kontrakt bez opiekuna liczy się jako `no_owner`, kolejka ma
  własną eskalację), „Zespół opiekunów”, opiekun na kafelkach spraw i grupa „opiekun”
  w komunikatach. `{opiekun}` w komunikacie bez opiekuna podstawia adres skrzynki,
  a mail powitalny wychodzi bez podpisu — oba zapasy już były.
- Opiekun wpisany ręcznie albo z importu zostaje (20.11: 44 kontrakty, TCM i Finanse).
  Ręczny przydział DL-a jako opiekuna działa jak dotąd.
- Uprawnienia się nie zmieniają: kartę opinii, popytu i rytm DL zmienia jako DL klienta
  (portfel), nie jako opiekun.

## Tablica „Do zrobienia”

- Z modułem karty rozmów i decyzji powstają tylko dla kontraktów z opiekunem, w obu
  zakresach („Moje” i „Wszystkie”). Konsultant bez opiekuna jest w kolejce back office'u,
  więc u DL-a zostają opinie menedżerów, popyt i dane klienta.
- Karta opinii menedżera bez opiekuna konsultantów pokazuje jako prowadzącego DL-a klienta
  (pierwszego z `client_leads`, jak przy popycie), żeby nie wpadała do „Bez osoby”.
- Front: nad tablicą jedno zdanie, że rozmowy, kontakt 7. dnia i „co dalej po projekcie”
  prowadzi kolejka. Chip „Moi podopieczni” przy module widać tylko z podopiecznymi albo
  włączony. To świadomy wyjątek od warunku „kanban 1:1” z 22.10 — decyzja Artura z 20.11;
  znacznik w inwentarzu zostaje.

## Konsultanci i zdrowie relacji

- Z modułem nie ma rytmu: lista bez filtrów rytmu, bez kolumny „Rytm” i licznika
  „Rozmów w tym miesiącu według rytmów”. Kto nie ma podopiecznych, widzi cały zakres bez
  przełącznika „Moi / Mój zakres” i bez kolumn „Następna rozmowa” i „Opiekun”.
- Zdrowie (`care/health.py`): `HealthSignals.rhythm = False` przy module wyłącza dwie
  reguły rytmu — „rozmowa zaległa” i „brak rozmowy od N dni”. Zostają opinia menedżera,
  zadowolenie, „Do przepięcia” i koniec bez decyzji. U DL 27 „Uwaga” spadła z 296 do
  około 127 z 300 osób (zostaje „zamówienie kończy się za N dni, bez decyzji”).

## Karta konsultanta i panel tablicy

- Z modułem karta (`care/card.py`, panel `/care?contract=` i zakładka „Opieka”
  kontraktu) ma `cadence: null` i nie podpowiada „Podnieś rytm”. Następny krok
  liczy się bez otwartych rozmów z rytmu (`kind = cadence`, punkty sprzed modułu;
  na kopii z 19.11 1 084 zaległe), więc nie mówi „zaległe 45 dni · Rozmowa według
  rytmu”. Punkty zostają w planie jako historia.
- Front (`careWithoutRhythm`): bez „Rytm kontaktu” w „Więcej” i bez „Zmień rytm”,
  punkt z rytmu nie jest „po terminie” (`planItemOverdue`), a „najbliższy”
  w nagłówku planu pomija rozmowy z rytmu sprzed dziś (`nearestPlanItem`). Kamienie
  (dzień 7, przed końcem) dalej bywają po terminie. Panel karty na tablicy: bez
  wiersza „Rytm” w „Konsultant w skrócie” i bez „Zmień rytm”.
- Kafelki tablicy się nie zmieniają: rozmowa z rytmu u kontraktu z opiekunem
  (19.11: 52 punkty) dalej stoi jako „N dni po”, bo to kolejka pracy opiekuna.
  Znikną po kroku 5 runbooka (niżej).

## Czego ta zmiana nie robi

- Nie zamyka zaległych punktów planu. Krok 5 runbooka back office'u
  (`close_overdue_contact_plan --apply`, 20.11: 1 181 punktów) należy do startu kolejki
  i wymaga zgody Artura.
- Nie zmienia dzwonków „Uzupełnij strukturę klienta” i „Popyt u klienta” — to zadania
  DL-a (decyzje z 18.10 i 22.10).
- Nie wprowadza rytmu rozmów ani kontroli zapisu rozmów (Artur 09.11: „Zostaw”).

Testy: `tests/test_care_board.py` (`test_back_office_*`, w tym karta bez rytmu), `tests/test_care_health.py`,
`tests/test_care_owner_pool.py`, front `components/care/__tests__/back-office-care.test.ts`.
Testy łańcucha z DL-em uruchamiają się bez modułu (`care_on` w `test_care_board.py`,
`care_on_lead_owner` w `test_admin_cases_care.py`).
