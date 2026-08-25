# Bank Pocztowy + BIK — cztery tickety zamówień i kontraktów

Data: 2026-08-25 · Gałąź: `claude/bank-pocztowy-bik-fixes-28b9ff` · Migracja: `0242`

Jeden PR obejmujący cztery zgłoszenia. **Dwa z nich miały błędną diagnozę**
w treści ticketu — poniżej jest wprost napisane, co okazało się prawdą i dlaczego
poprawka wygląda inaczej, niż zakładało zgłoszenie.

## Fakty produkcyjne, na których stoi ta zmiana

Ustalone odczytem żywego API (nie z założeń):

| co | wartość |
|---|---|
| Bank Pocztowy S.A. | `client_id=16`, **`multi_consultant_orders_enabled=false`** → widok `OrdersAndContractsTab` |
| BIK | `client_id=18`, multi=true → `MultiConsultantOrdersTab` |
| BP: kontraktorzy | 15 sztuk, **14 `active`**, wyłącznie kontrakt **#600** (Wojciech Sokolnicki) `draft` |
| Michał Leśniak | grupa **55** = `4500030067` (`active`, linia 150 `completed`, MD **13,75 z 13,75**), grupa **56** = `4500029903` (`active`, **`predecessor_group_id=55`**) |
| Maciej Koc (wzorzec poprawny) | grupa **53** z zagnieżdżoną **54** w statusie **`scheduled`** |
| Umowa B2B `1476/2026` | `signed_both`, `client_name='Bank Pocztowy S.A.'`, ale `client_id=41`, `job_id=115931`, `contract_id=560` — **wszystko wskazuje Energę** |

## T1 — przycisk „Zakończ" (Bank Pocztowy)

**Ticket zakładał**, że winna jest ścieżka tworzenia i że trzeba „uruchomić
skrypt naprawczy na istniejących rekordach".

**Faktyczna przyczyna:** bramka RENDERU wymagała `contract_status ∈ {active, ending}`,
a Flow B (`POST /clients/{id}/contract-with-order`) **świadomie** zakłada szkic —
dialog nie zbiera typu umowy ani trybu pracy. Do tego `ACTIVATION_REQUIRED_FIELDS`
wymaga `end_date`, więc kontrakt **bezterminowy** (profil body-leasingu BP)
**nie może zostać aktywowany żadną istniejącą ścieżką**. Nie jest to więc rekord
do naprawienia — to stan, w którym takich kontraktów będzie przybywać.

**Poprawka:** bramka stoi teraz na stanach TERMINALNYCH — „Zakończ" znika
wyłącznie dla `ended` i `void`. Backend był gotowy: `POST /contracts/{id}/terminate`
nie ma żadnej bramki statusu, a `draft → ended` jest legalną krawędzią cyklu życia.

**Migracja danych nie była potrzebna** — poprawka bramki naprawia wszystkie
rekordy naraz, obecne i przyszłe. Aktywowanie kontraktów SQL-em byłoby obejściem
cyklu życia przy brakujących polach.

Dodane pokrycie: `test_terminating_an_open_ended_draft_is_accepted` — nikt nigdy
nie wysłał tego żądania (przycisk był schowany), więc nic nie pilnowało, że
`draft → ended` przechodzi. Bez tego testu przycisk mógł zostać kosmetyką.

## T2 — statusy zamówień MD sterowane MD, nie datą

`dl_portal_expiry_scanner._promote_statuses` zamykał **każdą** linię z minioną
`end_date`, bez rozróżnienia trybu MD. Dołożony warunek `md_total IS NULL`.

Nowy helper `sync_md_line_status`: linia MD zamyka się przy `md_remaining <= 0`
i wraca do `active`, gdy budżet wróci. Dyskryminator, dzięki któremu nie
wskrzeszamy nikogo zamkniętego świadomie: linie domknięte datą, terminacją
kontraktu, ręcznym zamknięciem grupy albo zamianą kontraktora **zawsze niosą
`end_date` w przeszłości**.

**Brakujące ogniwo ze zgłoszenia:** `reopen_order_group` przywracał grupę, ale
**nie ruszał linii** — dokładnie stan Leśniaka (grupa `active`, linia `completed`).
Teraz reopen wskrzesza linie z pozostałym budżetem.

## T3 — struktura obecne/przyszłe, podział MD, historia

**Ticket zakładał**, że para Leśniaka to „dwa niezależne, rozłączone zamówienia"
i że trzeba je połączyć. **W bazie powiązanie ISTNIAŁO** (`predecessor_group_id=55`).
Zepsuty był wyłącznie **status**: grupa 56 stała jako `active`, a warunek
zagnieżdżenia wymaga `scheduled`.

Skąd się to wzięło: `extend_order_group` tworzy następcę jako `scheduled`, ale na
końcu woła materializator, a start (2026-08-15) był już przeszły w dniu utworzenia
(2026-08-21) — następca został natychmiast promowany, poprzednik domknięty,
a operator przywrócił potem samą grupę.

- **3.1/3.2 — przejście wyłącznie po wyczerpaniu MD.** Data startu następcy
  pozostaje warunkiem KONIECZNYM, ale przestaje być wystarczającym. Rodziny
  kosztowe i bez MD zachowują zachowanie czysto datowe.
  **Bez tej zmiany sama naprawa danych byłaby bezużyteczna** — materializator jest
  wołany przy KAŻDYM odczycie listy, więc cofałby korektę w kółko.
- **Podział zużycia:** nadwyżka ponad budżet bieżącego zamówienia przechodzi na
  linię następcy; brak jednoznacznego następcy → **system nie zgaduje**, nadwyżka
  zostaje jako ujemna pozostałość. Pojemność liczona z pominięciem rozliczanego
  miesiąca — inaczej powtórka importu przesuwałaby MD drugi raz.
- **3.3 — historia.** Wpisy techniczne ukryte **filtrem przy odczycie**, nigdy
  przez zawężenie domeny CHECK-a (`edycja_reczna` i `przedluzenie` mają wiersze na
  produkcji; zwężenie wywaliłoby `ADD CONSTRAINT`). `event_count` liczony **tym
  samym predykatem** — inaczej licznik obiecywałby 6 wpisów nad listą dwóch.
  Nowy typ `transfer_md` z ikoną i klikalnym numerem; `related_group_id` /
  `related_order_number` stoją **poza redakcją payloadu**, żeby odsyłacz nie
  znikał rolom bez `VIEW_FINANCE`.

## T4 — usuwanie projektu Energa

**Ticket zakładał**, że walidacja sprawdza podpis „na poziomie całego kontraktu
nadrzędnego, a nie per projekt". **To nieprawda.** `hard_delete_blocker` pyta
wyłącznie po `contract_id`, czyli **już jest per projekt** — projekt to osobny
wiersz `Contract`, a konsolidacja kontraktorów po `candidate_id` jest tylko
warstwą prezentacji i nie zaciąga rodzeństwa.

**Prawdziwy stan:** umowa `1476/2026` jest strukturalnie umową **Energi**
(klient 41, oferta 115931, kontrakt 560) i tylko drukowana nazwa strony mówi
„Bank Pocztowy S.A.". Dziennik statusów jest PUSTY, więc nie jest to znany
rozjazd po reaktywacji. Blokada działała **poprawnie** — chroniła projekt,
do którego umowa jest przypięta.

Rozstrzygnięcie (decyzja właściciela produktu, na podstawie przedstawionych
dowodów): **dokument jest źródłem prawdy** — umowa zostaje przepięta na Bank
Pocztowy. Skutek uboczny jest korzystny: dotąd Bank Pocztowy **nie był chroniony
wcale**, bo żadna podpisana umowa na niego nie wskazywała.

Poprawki kodu, niezależne od tej jednej umowy:
1. **Reaktywacja przepina `contract_id`.** `update_generated_contract` przy
   `suspended → active` przepisywał `job_id`/`client_id`/`client_name` na nowy
   projekt, ale **zostawiał `contract_id`** na kontrakcie starego — to mechanizm,
   który tę klasę rozjazdu produkuje. Notatka „Poprzedni projekt zakończony…"
   nadal idzie na STARY kontrakt (przepięcie jest po jej zapisaniu).
2. **Blocker rozpoznaje jawny rozjazd.** Podpis nie chroni wiersza, gdy
   `b2b.client_id` wskazuje **innego** klienta. `client_id IS NULL` **nadal
   chroni** — umowy standalone i historyczne (0196 bez backfillu) nie mają
   klienta, a gołe porównanie zdjęłoby z nich ochronę.
3. **Odpinanie przed DELETE to dokładne dopełnienie blockera** (`not_(...)`) —
   FK jest `RESTRICT`, więc rozjazd tych dwóch reguł kończy się 500-tką zamiast
   czytelnej odmowy.

**Projektu Energa migracja NIE usuwa.** Kasowanie kontraktu ciągnie kaskadę
(dokumenty, aneksy, harmonogramy, faktury, linie zamówień) i jest nieodwracalne;
po przepięciu umowy operator usuwa pusty projekt z interfejsu, widząc, co usuwa.

## Migracja 0242 i lustro w `entrypoint.sh`

Prod ma `alembic_version` osierocony na `0152`, więc **sama migracja jest tam
no-opem** — realnym mechanizmem wdrożenia jest `entrypoint.sh`. Oba warianty są
w PR-ze i oba zostały wykonane na kształcie odtworzonym z produkcji.

Asymetria jest świadoma i przybita testem: **migracja przerywa `RAISE`-em**, gdy
rozpozna cel, którego nie umie ruszyć; **lustro NIE MOŻE** — tam wyjątek wywraca
cały blok razem z markerem, a jedynym śladem jest linijka „backfill data skip"
przy zielonym `/api/health`.

Trzy korekty: grupa `4500029903` → `scheduled` (+ linie → `draft`), linia
`4500030067` → `active` (MD niewyczerpane), umowa `1476/2026` → kontrakt BP.

## Weryfikacja

| Bramka | Wynik |
|---|---|
| Frontend `vitest` (pełny, serial) | **1608/1608** (baza: 1596/1596) |
| Frontend `tsc --noEmit` | zielone |
| Frontend ESLint + dead-code gate | zielone |
| Backend `ruff check app/` + `format --check` | zielone |
| `alembic upgrade heads` na świeżej bazie | zielone |
| Bramki 0242 | 18/18 |
| Migracja na odtworzonym kształcie produkcji | 4/4 korekty, idempotentna, fail-closed działa |

Migracja została wykonana na zasianych danych i sprawdzona wynikowo: grupa 56 →
`scheduled`, linia 150 → `active` (13,75 MD), linia 151 → `draft`, umowa 63 →
kontrakt 600. Powtórzenie: no-op. Na nierozpoznanym kształcie: `RAISE` **bez
skonsumowania markera**. Lustro z `entrypoint.sh` daje identyczny wynik i milczy
tam, gdzie migracja krzyczy.

## Błędy złapane w trakcie, których warto nie powtórzyć

1. **`op.execute` z dwiema instrukcjami** (`DROP…; ADD…`) — asyncpg przygotowuje
   każdą instrukcję i odrzuca sklejone (`cannot insert multiple commands into a
   prepared statement`). Wywaliłoby `alembic upgrade heads` na każdym PR-ze.
2. **Migracja przerywała na PUSTEJ bazie.** „Nie ma czego poprawiać" to nie to
   samo co „rozpoznaję cel, ale nie umiem go ruszyć". Pierwsza wersja myliła te
   stany i zabiłaby CI oraz każde nowe środowisko. Każdy `RAISE` siedzi teraz pod
   warunkiem „sonda coś ZNALAZŁA".
3. **`vi.spyOn(Element.prototype, "scrollIntoView")` bez przywrócenia.**
   `setup.ts` instaluje tam no-op, bez którego cmdk nie montuje się w jsdom;
   szpieg wyciekał poza plik i wywracał **cudzy** test w innym pliku. Objaw był
   mylący — padała nie ta sekcja, która coś popsuła.

## Znane ograniczenia

- **Treść wpisu `transfer_md` bywa nieprecyzyjna przy kilku konsultantach na
  jednym zamówieniu** — wpis powstaje per konsultant, a zdanie mówi „Zamówienie
  zakończone". Sam mechanizm jest poprawny (bramka sumuje wszystkie linie),
  kłamie tylko zdanie.
- **Kaskada transferu obejmuje JEDEN skok.** Nadwyżka przekraczająca budżet
  następcy zostaje u niego jako ujemna pozostałość.
- **`reopen` nie cofa dat na liniach** — zamówienie zakończone z datą w przeszłości
  wraca jako grupa `active`, ale linie zostają zamknięte. Uznane za poprawne
  (data zakończenia była świadomą decyzją), ale to decyzja produktowa do
  potwierdzenia.
- **Ostatni krok T4 należy do operatora** — usunięcie projektu Energa z interfejsu
  po wdrożeniu.
