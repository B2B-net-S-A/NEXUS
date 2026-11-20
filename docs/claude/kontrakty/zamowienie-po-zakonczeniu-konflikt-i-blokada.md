# Klient zamówił okres po zakończeniu: konflikt do decyzji i blokada linii (19.11.2026)
<!-- indeks: `services/contract_order_after_end.py`, karta „Co się dzieje”, kubełek `bucket=order_after_end` i pigułka „Zamówione po końcu”, dzwonek DL-a raz na zamówienie, okres kontraktu bez szkicu wstrzymanego wypowiedzeniem, 422 dla linii na zakończonej umowie nie-B2B -->

Decyzja Artura z 19.11.2026: wariant „Konflikt do decyzji + blokada”. Na
produkcji (odczyt 19.11) na 82 kontraktach „Kończący się” i „Zakończony” dwa
miały żywe zamówienie po końcu projektu:

- kontrakt B2B kończący się 30.11.2026 dostał 30.10 z poczty szkic zamówienia
  na 01.12.2026–31.05.2027. Bramka `order_mail_signature.termination_allows`
  celowo go nie aktywowała, ale nikt nie dostał sygnału, a synchronizacja
  pokazywała koniec zamówienia u klienta 31.05.2027;
- umowa zlecenie zakończona 31.10.2026 dostała 02.11 aktywną linię MD
  w zamówieniu zbiorczym. Zamówienie nie wskrzesza umowy nie-B2B z datą końca,
  więc osoby nie było w aktywnych kontraktach ani w MRR.

## Reguła konfliktu

Jedna funkcja (`services/contract_order_after_end.py`) zasila kartę, kubełek
listy i dzwonek:

- kontrakt „Kończący się” albo „Zakończony”;
- koniec projektu = `end_date`, a gdy jej brak, `terminated_at`;
- zamówienie inne niż anulowane i zakończone, którego koniec jest pusty albo
  późniejszy od końca projektu.

Zakończone zamówienie po końcu projektu to rozliczona historia, nie decyzja,
więc karty nie daje. B2B „Kończący się” z zamówieniem w okresie nie ma
konfliktu.

## Gdzie to widać

- **Strona kontraktu:** pozycja w pasie „Co się dzieje”
  (`lib/contract-happening.ts`, `order_after_end` z `GET /api/contracts/{id}`),
  jedna na zamówienie. Wyjścia to istniejące ścieżki:
  - B2B: „Cofnij zakończenie…” (panel cofnięcia, Admin/Finanse/TCM); przy
    konflikcie ten przycisk znika z pozycji końca współpracy, żeby nie stał
    dwa razy;
  - umowa zlecenie i o pracę: „Przedłuż aneksem” (zakładka „Aneksy”);
  - linia zamówienia zbiorczego: „Przypisz innej osobie” prowadzi do panelu
    zamówienia (`?tab=zamowienia&group=`), gdzie jest „Zamień kontraktora”.
    Zamówienia pojedynczego nie da się przepiąć na inną osobę, więc jest
    „Edytuj zamówienie” (`?tab=zamowienia&order=`);
  - szkic zamówienia pojedynczego: „Anuluj szkic” (PATCH ze statusem
    „Anulowane” po potwierdzeniu `useConfirmV2`; szkic zostaje w historii
    z plikiem).
- **Lista kontraktów:** pigułka „Zamówione po końcu” (`bucket=order_after_end`,
  adres `?after_end=1`) stoi w rzędzie tylko wtedy, gdy zbiór nie jest pusty.
  Wiersz ma notkę „po końcu: szkic zamówienia 01.12.2026 – 31.05.2027”
  (`order_after_end` w wierszu, także z umów w `group_members`).
- **Dzwonek DL-a klienta:** `contract_alerts._notify_orders_after_end`
  w dobowym cyklu, typ `contract_ending` (kategoria „Kontrakty”, bez migracji
  enuma), odbiorcy z `DeliveryAlertRecipientScope.bell_recipients`. DL ma
  decyzję, więc spełnia `powiadomienia/dl-tylko-dzwonki-z-zadaniem.md`. Raz na
  zamówienie i koniec projektu: klucz `order_after_end:{zamówienie}:{koniec}`
  w `contract_alert_dedup`. Nowy koniec projektu to nowa decyzja i nowy dzwonek.
  Wiersz dzwonka nie ma `related_entity_*`, bo `ix_notif_dedup_daily` nie zna
  typu encji: id zamówienia zderzało się z id kontraktu z alertu końca umowy
  z tego samego dnia i dzwonek przepadał po cichu (złapał to test na wspólnej
  bazie). Powtórki pilnuje sam klucz.
- **Dobowy cykl przelicza też okres** kontraktów ze szkicem wstrzymanym
  wypowiedzeniem (`_resync_held_draft_periods`), bo okres zapisany przed tą
  regułą zostałby do pierwszego zapisu zamówienia.
- **Przy 1280 px** pigułka zajmuje miejsce, którego rząd nie ma: gdy jest
  widoczna, „Zamówienia z maila” schodzi do drugiego rzędu (jak przy
  ostrzeżeniu o szkicach). Pigułka stoi tylko przy konflikcie.

## Synchronizacja okresu

`contract_order_sync` bierze okres zamówienia (`client_order_start_date`,
`client_order_end_date`) z najnowszego uzupełnionego zamówienia **bez szkicu
wstrzymanego wypowiedzeniem** (`_period_source`: szkic, którego
`termination_allows` nie pozwala aktywować). Tak samo działa nocne
uzupełnianie okresu (`backfill_missing_order_periods`). Gdy zostaje sam taki
szkic, okresu nie ma. Stawkę i jednostkę nadal niesie najnowsze zamówienie ze
wszystkich uzupełnionych. Po „Cofnij zakończenie” bez daty końca wypowiedzenie
nie obowiązuje i szkic znów daje okres.

## Blokada linii zamówienia zbiorczego

Żywa linia na umowie nie-B2B, która jest „Zakończona” albo ma `end_date`
przed startem linii, dostaje 422 z komunikatem „Umowa zlecenie zakończyła się
31.10.2026 — przedłuż ją aneksem albo załóż nowy kontrakt” (umowa o pracę:
„Umowa o pracę zakończyła się …”; data końca jeszcze przed nami: „kończy się
30.11.2026”). Bramka `_assert_agreement_accepts_line`
w `api/client_order_groups.py` stoi przy:

- dodaniu linii (`_build_line`: nowe zamówienie z liniami, „Dodaj osobę”,
  dodanie kilku osób, linie przedłużenia);
- zamianie kontraktora i przejęciu (kontrakt nowej osoby, dzień zamiany albo
  wejścia);
- aktywacji szkicu linii w `update_line`.

Zapis historyczny (`historical: true`) bramki nie przechodzi, bo opisuje
przeszłość. Umowa B2B wraca sama (powrót po przerwie), więc jej to nie
dotyczy. Nocny materializator zamówień zaplanowanych (`order_group_lifecycle`)
nie odmawia, bo nie ma komu; linię po końcu takiej umowy pokaże karta konfliktu.

Poprawki danych dwóch przypadków z produkcji robi DL (lista w raporcie sesji).

Testy: `backend/tests/test_contract_order_after_end.py`,
`frontend/src/lib/__tests__/contract-happening.test.ts`,
`frontend/src/components/v2/pages/__tests__/ContractsListV2OrderAfterEnd.test.tsx`,
`frontend/src/components/contracts/detail/__tests__/CancelOrderDraftButton.test.tsx`.
