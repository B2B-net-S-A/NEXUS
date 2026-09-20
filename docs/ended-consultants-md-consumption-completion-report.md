# Zakończeni konsultanci: „Zakończone" + doliczanie zużycia z późniejszych importów

Data: 2026-09-20. Zgłoszenie dotyczyło zamówienia **CeZ/242/2025** (grupa 96,
klient 115 — Centrum e-Zdrowia, `end_date` NULL, budżet MD per osoba).

## Co było nie tak

Ticket składał się z dwóch spraw o bardzo różnym stanie.

**Część 1 — podział „Aktywni" / „Zakończone" — działała już w 90 %** (PR #1573,
16.09). Serwer liczy `is_line_on_active_roster`, karta dzieli obsadę po polu
`OrderLineRead.is_active` i sortuje zakończonych malejąco datą zejścia. Odczyt
produkcji potwierdził, że linie 675/677/678 grupy 96 mają `status=completed`,
więc były już w dolnej sekcji.
**Dziura była jedna:** karta celowo **przypinała do sekcji aktywnej** każdą
linię z nierozstrzygniętą sprawą offboardingu — a taką sprawę zakłada KAŻDE
normalne zakończenie współpracy przez kontrakt. Linie CeZ jej nie miały tylko
dlatego, że powstały z zasiewu danych startowych; u każdego innego klienta
zakończony konsultant nadal wisiał w „Aktywnej obsadzie".

**Część 2 — doliczanie zużycia po przeniesieniu — nie działała wcale.** Import
miesięczny szukał linii wyłącznie wśród `status == active`. Osoba przeniesiona
do „Zakończone" była dla importu niewidzialna: raport za miesiąc, w którym
pracowała, lądował jako „Brak aktywnego zamówienia" i **nie dawał się przypisać
nawet ręcznie**. Przykładem z ticketu jest dosłownie linia 678 (`md_total` 356,
jedno zejście 4 MD za 2026-03, `md_remaining` 352, `status=completed`).

## Zasada, na której stoi poprawka

> Obsada zamówienia to **prezentacja** (`is_line_on_active_roster`).
> Kwalifikacja do importu to **okres**, nie status: linia rozlicza miesiąc M,
> jeżeli jej okres obejmuje M, jej kontrakt nie jest `void`, a grupa rozlicza M.

Wzorzec istniał już w repo — replay paczki Polkomtela
(`_historical_period_conditions`) od dawna liczył „czy linia była ważna w tamtym
miesiącu". Ta zmiana promuje go do zwykłej ścieżki importu zamiast zostawiać
wyjątkiem.

**Poszerzenie jest bezpieczne, bo linia zakończona to cel ZAPASOWY, nigdy
konkurent dla aktywnej.** Gdy nazwisko trafia w obie, wygrywa aktywna
(`match_by_name`), więc dzisiejsze automatyczne dopasowania nie zmieniają się
ani o jeden wiersz — nowe zachowanie dotyczy wyłącznie osób, które nie mają już
żadnej aktywnej linii.

## Zmiany

### Backend

* `services/client_order_lines.py`
  * nowa para `line_settles_in_month_conditions` (SQL) + `line_settles_in_month`
    (Python) — status `active`/`completed` (`draft` tylko dla kosztowych),
    okres nachodzący na miesiąc, kontrakt nie `void`;
  * `active_md_lines` / `active_cost_lines` / `active_shared_md_lines`
    przemianowane na `md_lines_settling_in_month` /
    `cost_lines_settling_in_month` / `shared_md_lines_settling_in_month`
    i przestawione na nowy predykat. **Nazwa była jedynym realnym konsumentem
    starej reguły poza importem** (wszystkie pozostałe trafienia to komentarze),
    więc zostawienie jej znaczyłoby zaproszenie do ponownego zawężenia;
  * `_historical_period_conditions` reużywa nowy predykat (replay dokłada tylko
    okres GRUPY i zgodność klienta kontraktu);
  * `match_by_name` — preferencja dokładnie jednej linii aktywnej;
  * `sync_md_line_status` — nowy warunek `_has_open_offboarding_case`: zaległe
    rozliczenie **nie wskrzesza** linii czekającej na decyzję DL;
  * `recompute_remaining` — `_refresh_open_offboarding_snapshot`: MD dopisane po
    zejściu zmniejszają `remaining_md_snapshot` otwartej sprawy, żeby
    przeniesienie puli nie oddało komuś dni, które odchodzący już wypracował.
* `api/md_consumption.py` — te same trzy bramki, które wcześniej pytały o
  `active`: `_ordinary_locked_target_is_valid`, `_apply_to_line` (obie ścieżki,
  zwykła i replay, mają teraz JEDEN warunek linii) oraz `assign_row` (ręczne
  przypisanie przyjmuje linię zakończoną; 409 zostaje dla anulowanej i dla
  okresu spoza miesiąca, z komunikatem mówiącym prawdziwy powód).
* `models/md_consumption.py` — etykieta wiersza `unmatched`: „Brak aktywnego
  zamówienia" → **„Brak pasującego zamówienia"** (stara wysyłała operatora po
  odblokowanie statusu, o który nikt już nie pyta).
* `services/contract_order_offboarding.py` — komentarz „MD always becomes
  non-matchable for future imports immediately" przestał być prawdą i został
  zastąpiony opisem nowej reguły.

### Frontend

* `OrderGroupCard.tsx` — podział obsady jest teraz czystą funkcją `is_active`
  (plus szkice w grupie `draft`). Wyjątek dla `offboarding_case.status ===
  "pending"` **zdjęty świadomie** (decyzja Artura, 18.09) — panel decyzji jedzie
  z wierszem do „Zakończone", a nagłówek sekcji niesie licznik:
  **„Zakończone · 2 wymagają decyzji"**.

### Dokumentacja

* `app/data/procedures/zamowienia-instrukcja-delivery-lead.md` — nowe akapity:
  decyzja o pozostałych MD czeka w „Zakończonych"; zakończenie współpracy nie
  wyklucza z importu; rozstrzygnięcie miesiąca przejścia między zamówieniami.
  Instrukcja przestemplowana (`scripts/stamp_orders_procedure.py`).

## Czego celowo NIE ruszono

* `is_line_on_active_roster` — reguła prezentacji bez zmian; jej docstring
  wprost zabrania zlewania z regułą importu.
* Sumy grupy `md_used_total` / `used_value_pln` — **nigdy nie filtrowały po
  statusie linii**, więc doliczone MD wchodzą do „Wykorzystano X / Y MD" i do
  wartości umowy same z siebie. Kryterium 6 ticketu spełnione bez zmiany kodu,
  ale przypięte testem.
* `md_positions_total` / reguła pozycji (`cancelled` odpada, `replacement`
  odpada, `swap` wnosi samo zużycie).
* Pigułki zakładki „Aktywne"/„Zakończeni" — filtrują CAŁE grupy i kontraktorów
  po statusie umowy, to inna warstwa niż podział obsady wewnątrz karty.
* `apply_contract_order_offboarding` nadal ustawia `status = completed`.

## Weryfikacja

Testy backendu (obraz `nexus-deps-test`, Postgres z migracjami do `heads`):

* `tests/test_md_consumption_ended_line.py` — **przypadek z ticketu**: linia
  `completed` z `md_total` 356 i zapisanymi 4 MD przyjmuje zaległy raport →
  `md_used` 25, `md_remaining` 331, linia **nadal** `completed`,
  `md_used_total` grupy 25, `used_value_pln` 25 × stawka. Do tego: anulowana
  linia nie przyjmuje nic, a przy konflikcie „aktywna vs zakończona" wygrywa
  aktywna i wiersz nadal dopasowuje się automatycznie.
* `tests/test_md_line_revive_guard.py` — otwarta sprawa offboardingu trzyma
  linię zakończoną (z kontrolą negatywną: bez sprawy budżet nadal ją wskrzesza)
  i migawka puli podąża za realną pozostałością.
* `tests/test_md_consumption_offboarding_lock.py` — przepisany: bramka pod
  blokadą wiersza nadal odrzuca linię anulowaną, linię z okresem sprzed
  miesiąca i linię przeniesioną do innej grupy.
* Regresja: `test_order_line_roster`, `test_md_import_*`, `test_md_optional_scope`,
  `test_line_consumptions_api`, `test_order_lifecycle_and_cost`,
  `test_explicit_order_types`, `test_order_activation_gates_and_group_materializer`,
  `test_bik_md_exhaustion_lifecycle`, `test_multi_consultant_orders` i sąsiednie.

Frontend: `OrderGroupCard.roster.test.tsx` (4 przypadki: pending w
„Zakończonych", licznik decyzji, brak licznika bez spraw, zastępca zostaje
w obsadzie) + `npm run type-check`.

Bramki repo: `ruff check app/`, `ruff format --check app/`,
`scripts/stamp_orders_procedure.py`.

### Po wdrożeniu

Linia **678** grupy 96 jest żywym fixture'em kryterium akceptacji
(`md_total` 356, `md_remaining` 352, `status=completed`). Import rozliczenia za
miesiąc objęty jej okresem musi ją zaproponować jako cel, a po zapisie
`md_remaining` = 352 − zaimportowane MD. Zapis wykonuje Delivery/Finanse przez
interfejs — danych nie ruszamy SQL-em.

## Poza zakresem (świadomie)

Rozszerzenie `group_settles_in_month` o grupy `exhausted` bez `closure_date` —
osobna decyzja o tym, czy wyczerpane zamówienie ma jeszcze przyjmować zaległe
rozliczenia.
