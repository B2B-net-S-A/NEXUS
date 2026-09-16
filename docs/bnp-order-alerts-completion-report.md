# BNP Paribas — dwa niezależne powiadomienia o kończącym się zamówieniu

Ticket (09.2026): Delivery Lead ma dostawać osobny sygnał o **końcu okresu**
zamówienia i osobny o **wyczerpywaniu się MD**, nigdy połączone w jedną kartę.
Dotyczy wyłącznie klienta BNP Paribas Bank Polska S.A.

## Co naprawdę było zepsute

Ticket opisywał stan jako „mechanizm opiera się głównie na dacie końca".
Odczyt kodu pokazał co innego — zamówienia BNP to **linie zamówień
wielo-konsultantowych** (`client_orders.order_group_id IS NOT NULL`), a te są
obsługiwane inaczej niż zamówienia okresowe:

| Sygnał | Dzwonek (`notifications`) | Karta w panelu „Moi klienci" (`dl_alerts`) |
|---|---|---|
| Koniec okresu | działał — `dl_portal_expiry_scanner._scan_orders` nie filtruje po grupie, a linia dziedziczy `end_date` grupy | **brak** — `rule_periodic_order_ending` miała warunek `order_group_id IS NULL`. To ta karta niesie maila i powtórkę co 7 dni; dzwonek daje jeden sygnał na próg i nie powtarza |
| Kończące się MD | — | tylko `md_budget_low`: próg **bezwzględny 21 MD** liczony od `md_remaining`, czyli od podstawy **razem z zakresem opcjonalnym**. Przy zamówieniu na 220 MD to ~90% zużycia |

Czyli: karty o końcu okresu BNP nie miał w ogóle, a sygnał o MD przychodził
dużo za późno na wynegocjowanie i wystawienie nowego dokumentu PO.

## Rozwiązanie

**Bramka klienta** — `EXTENDED_ORDER_ALERT_CLIENT_IDS` (CSV, fail-closed),
odczytywana przez `app/services/order_alert_policy.py`. Pusta lista zostawia
obie reguły w stanie sprzed rewizji, u wszystkich klientów.

Świadomie env, a nie zaszyte `BNP_CLIENT_ID = 12`: „BNP" to **rodzina rekordów**
klienta (osobne wiersze oddziału i banku, do tego Cardif — patrz
`order_policies/known_clients.py` i audyt `/api/admin/client-mixups`), więc id
właściwej spółki ustala się na produkcji. Nie reużyto też
`BNP_ORDER_EXTRACTION_CLIENT_IDS` z rejestru polityk PDF — zdjęcie klienta
z polityki **odczytu dokumentów** po cichu zabrałoby mu alerty.

**1. Karta „kończy się okres" dla linii zamówień grupowych.** Rozszerzenie
istniejącej `rule_periodic_order_ending` zamiast nowej reguły: zero nowej
mechaniki, zero migracji, zero zmian w unii typów na froncie. Warunek
`order_group_id IS NULL` → `or_(order_group_id IS NULL, client_id IN extended)`
plus wymóg `ClientOrderGroup.status == active` (karta „kończące się" pod
zamówieniem zakończonym przeczyłaby nagłówkowi, pod którym stoi). Reszta cyklu
bez zmian: mail przy pierwszym wierszu (`email_on_first`), powtórka co 7 dni,
`t14` mailem, `t7` na czerwono; `entity_key` niesie datę końca, więc
przedłużenie zamyka starą sprawę i zaczyna nową.

Etykieta typu zmieniona z „Kończące się zamówienie okresowe" na „Kończące się
zamówienie" — linia MD nie jest zamówieniem okresowym, a etykieta trafia do
raportu XLSX kart DL.

**2. Nowy typ `md_base_usage_high`** — zużycie **podstawy** MD (`md_total`) ≥
`DL_ALERT_MD_BASE_USAGE_PERCENT` (80%), per konsultant, sekcja `ending`.

* Zakres opcjonalny (`md_optional_total`) nie wchodzi **ani do licznika, ani do
  mianownika** — ticket pyta o podstawę, a opcja jest rezerwą z umowy.
* Zużycie liczone z **sumy zejść** (`client_order_md_consumptions`), nie
  z `md_remaining`: ta niesie też `md_manual_adjustment`, czyli korektę
  **budżetu**, więc wyprowadzenie z niej przesunęłoby próg o wartość korekty.
* Podział podstawa/opcja przez `split_md_usage` — jedyne miejsce w repo
  definiujące „podstawa najpierw, nadwyżka do opcji"; te same liczby pokazują
  paski `MdScopeBars` na karcie zamówienia.
* **Bez eskalacji i bez maila.** Wysoki priorytet (mail przy ~7 dniach roboczych
  zapasu) ma już `md_budget_low`; druga rosnąca ścieżka dla tej samej liczby to
  dwie karty krzyczące to samo.

**Próg 21 MD zostaje globalny i bezwzględny.** `md_base_usage_high` go nie
zastępuje ani nie konfiguruje per klient — „mało MD" ma znaczyć to samo
w każdym raporcie (pilnuje `test_md_threshold_is_global_not_per_client`).
W paśmie, w którym oba warunki są spełnione, DL widzi dwie karty: wczesną
i pilną. To jest zamierzone.

## Zmienione pliki

* `backend/app/services/order_alert_policy.py` — nowy, bramka klienta.
* `backend/app/core/config.py` — `EXTENDED_ORDER_ALERT_CLIENT_IDS`,
  `DL_ALERT_MD_BASE_USAGE_PERCENT`, parser CSV → `frozenset[int]`.
* `backend/app/models/dl_alert.py` — `ALERT_MD_BASE_USAGE_HIGH`, etykiety,
  mapa sekcji, `ck_dl_alerts_type`.
* `backend/alembic/versions/0317_dl_alert_md_base_usage_high.py` + **oba**
  lustra w `backend/entrypoint.sh` (`CREATE TABLE` i atomowy `DROP+ADD`).
* `backend/app/tasks/dl_alerts_scanner.py` — `rule_md_base_usage_high`,
  `_consumed_md_by_order`, rozszerzona `rule_periodic_order_ending`.
* `frontend/src/lib/api/dlAlerts.ts`, `MyClientsAlertsPanel.tsx` (pigułka
  „Podstawa MD"), harness `preview/dl-alerts`.
* Instrukcja DL + stempel, `CLAUDE.md`.

## Weryfikacja

* `tests/test_dl_alerts_bnp_order_alerts.py` — 15 testów: próg 80% domknięty
  (79% cisza, 80% karta), bramka fail-closed i odporna na literówki, zakres
  opcjonalny poza rachunkiem, `md_manual_adjustment` nie rusza progu, karta
  zamyka się przy dosypaniu podstawy, linia grupy w zamówieniu zakończonym
  pomijana, regresja zamówień okresowych, powtórka tygodniowa i odhaczenie —
  oraz cztery kryteria akceptacji z ticketu wprost.
* 238 testów regresji modułu zamówień/alertów zielone; `test_dl_alerts.py`
  (rejestr reguł, kontrakt progu 21 MD) zaktualizowany.
* Frontend: `type-check`, `lint`, `build` zielone; harness `/preview/dl-alerts`
  obejrzany w przeglądarce — dla „Bank Zeta" stoją **dwie osobne karty**
  („Podstawa MD" i „28 dni"), zgodnie z kryterium akceptacji nr 4.

## Aktywacja na produkcji

1. Ustal `client_id` dla „BNP Paribas Bank Polska S.A." —
   `GET /api/admin/client-mixups` pokazuje rodzinę „BNP *" z NIP-ami (szukany
   NIP `5261008546`). **Nie zgaduj.**
2. Workflow **„Coolify set env"** → `EXTENDED_ORDER_ALERT_CLIENT_IDS=<id>`
   (`redeploy=false`), potem jeden zwykły deploy.
3. Skaner budzi się co 24 h. Po biegu: `GET /api/dl-alerts/cards` jako DL BNP.

## Świadomie poza zakresem

Zmiana progu 21 MD, wspólna pula MD (`md_budget_mode='shared'` — nie zna
podziału na podstawę i opcję, a ci klienci nie są na liście), zamówienia
kosztowe, dzwonek (już obejmował te linie) oraz pozostali klienci
wielo-konsultantowi: BIK i Polkomtel mają zamówienia bezterminowe, więc reguła
datowa i tak by u nich milczała.
