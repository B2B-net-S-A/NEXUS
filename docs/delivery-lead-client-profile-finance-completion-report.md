# Delivery Lead widzi kwoty własnego portfela (profil klienta + portal DL)

**Data:** 2026-09-01 · **Zgłoszenie:** brak danych finansowych dla roli Delivery
Lead w profilu klienta (kolumny „Stawka kosztowa", „Stawka przychodowa", „Marża").

## Przyczyna

`GET /api/clients/{id}/profile` zerował stawki, marżę, MRR/LTV i widełki
otwartych rekrutacji dla każdego, kto nie ma capability `VIEW_FINANCE`
(`backend/app/api/clients.py`). Rola `delivery_lead` **nigdy jej nie miała** —
`ROLE_CAPABILITIES` daje jej `VIEW_OPERATIONAL_AGGREGATES`,
`VIEW_OWN_DELIVERY_KPI`, `VIEW_TEAM_KPI`, `VIEW_CLIENT_OPERATIONS` i
`VIEW_TENDERS_OPERATIONAL`. Komentarz przy tej redakcji od 2026-07-16 twierdził
„tylko dla VIEW_FINANCE (delivery_lead, admin)" — czyli opisywał zamiar, który
w macierzy uprawnień nigdy się nie znalazł.

Front nie miał z tym nic wspólnego: `ConsultantsTable` rysuje wszystkie kolumny
zawsze, a `null` renderuje jako „—". Objaw „puste kolumny" to backendowa
redakcja, nie ukryty widok.

## Potwierdzenie na produkcji (2026-09-01)

Zgłoszenie przyszło ze zrzutu ekranu: Nordea Bank Abp (`client_id=11`), czterech
konsultantów, trzy kolumny finansowe puste. Ten sam ekran, ten sam klient i ci
sami konsultanci odpytani z **sesji admina** (`view_finance`) zwracają komplet:

| Konsultant | Kosztowa | Przychodowa | Marża |
|---|---|---|---|
| Patryk Tatarek (`contract_id=520`) | 15 200,00 zł | 25 120,00 zł | 9 920,00 zł |
| Błażej Kanczkowski (522) | 14 400,00 zł | 20 960,00 zł | 6 560,00 zł |
| Piotr Ciszek (525) | 16 800,00 zł | 24 000,00 zł | 7 200,00 zł |
| Mateusz Polanski (526) | 21 600,00 zł | 28 480,00 zł | 6 880,00 zł |

Zmierzone dwiema drogami: `GET /api/clients/11/profile` oraz odczyt DOM-u
wyrenderowanej tabeli. **Dane źródłowe są kompletne, a backend liczy je
poprawnie** — pustki na zrzucie to redakcja po stronie odbiorcy bez
`VIEW_FINANCE`, czyli dokładnie ta ścieżka, którą ta zmiana otwiera dla DL.

Warto odnotować, co ta miara WYKLUCZYŁA: pierwszą hipotezą był brak stawek dla
kontraktów o starcie w przyszłości (Tatarek startuje 19.10.2026, a stawki
rozwiązuje się „na dziś"). Nie ta ścieżka — `_resolve_scheduled_rate` przy samych
przyszłych krokach zwraca najbliższy nadchodzący, więc świeży kontrakt ma stawkę.

## Poprawka

Nowy `_can_see_client_profile_finance(user, client_id, delivery_lead_client_ids)`
(`backend/app/api/clients.py`): finanse widzą role z `VIEW_FINANCE` **oraz**
Delivery Lead — wyłącznie u klienta z własnego portfela.

**`VIEW_FINANCE` NIE zostało nadane roli DL globalnie.** Ta capability steruje
40+ innymi powierzchniami (eksport kontraktów, przychody w `/my-clients`,
`/settings/clients-overview`, dashboardy zarządcze), więc dopisanie jej do
`ROLE_CAPABILITIES` otworzyłoby je wszystkie naraz. Zastosowany wzorzec jest
lustrem `_can_see_finance` z modułu zamówień: wąska powierzchnia zamiast
szerokiej capability.

Granica portfela (`resolve_delivery_lead_client_ids`) jest liczona raz
i podawana dwóm miejscom — guardowi dostępu i decyzji o finansach. Finanse nie
wiszą na tym, że `assert_delivery_lead_client_visible` nie rzuciło wyjątku
linijkę wyżej.

## Zakres — co ZOSTAJE zredagowane

| Rola | Stawki na profilu klienta | Dlaczego |
|---|---|---|
| admin, finance | widzą | mają `VIEW_FINANCE` |
| delivery_lead (przypisany) | **widzą — zmiana** | „Obecni konsultanci" to ich obsada |
| delivery_lead (obcy klient) | 403 na całym profilu | granica portfela |
| head_of_recruitment (+ hybryda HoR+DL) | zredagowane | nadzór nieoskopowany; repo trzyma HoR poza finansami |
| tac | zredagowane | jest w zespole klienta, ale obsady nie prowadzi |
| recruiter, sourcer | zredagowane | bez zmian |

Redakcja jest całościowa albo żadna. Kafel „Aktywne MRR" jest sumą kolumny
„Marża" pod nim, a „Archiwum konsultantów" ma dokładnie te same trzy kolumny co
zakładka obok — częściowe odsłonięcie rozjeżdżałoby ten ekran ze sobą samym.
Skutek uboczny, świadomy: DL widzi u swojego klienta także `salary_min/max`
otwartych rekrutacji w payloadzie profilu (dziś bez konsumenta w UI) oraz LTV.

## Marża

Bez zmian w liczeniu, zweryfikowana: `_finance_rates_in_pln` przewalutowuje obie
nogi na PLN **osobno**, potem odejmuje — `marża = przychodowa − kosztowa`. Nie
pochodzi z kolumny `contracts.margin` (ta niesie kwotę z ostatniego zapisu
kontraktu). Stawki idą z harmonogramów z fallbackiem na kolumny legacy, więc
„—" zostaje wyłącznie przy realnym braku danych źródłowych: brak stawki albo
brak kursu FX dla waluty obcej.

## Testy

`backend/tests/test_client_profile.py` — cztery nowe:

- `test_delivery_lead_sees_rates_and_margin_for_own_client` — trzy kolumny +
  tożsamość `marża == przychodowa − kosztowa` + kafel MRR,
- `test_delivery_lead_sees_the_same_columns_in_the_archive` — parytet zakładek,
- `test_delivery_lead_outside_the_portfolio_gets_403_not_rates` — granica,
- `test_head_of_recruitment_with_dl_role_stays_redacted` — zapora przed
  poszerzeniem na hybrydę HoR+DL.

`backend/tests/test_client_access_matrix.py` — `dl` i `multi_dl` mają
`financials=True`; `hor` i `tac` zostają na `False`.

**Dowód, że testy dotykają zepsutej ścieżki:** po cofnięciu poprawki
(przywrócenie gołego `user_has_capability(..., VIEW_FINANCE)`) przebieg to
`4 failed, 29 passed` — padają dwa nowe testy DL oraz `test_access_matrix[dl]`
i `[multi_dl]`. Z poprawką: `32 passed, 1 skipped`.

## Część druga: portal DL (`/my-clients`) — ta sama przyczyna

Zgłoszone jako sąsiad, rozstrzygnięte osobno i **naprawione** tą samą metodą.
`backend/app/api/my_clients.py` liczył `finance_ok = has_financial_access(user)`
w dwóch miejscach, więc `active_revenue`, `total_revenue_all_time`,
`currency_breakdown`, `monthly_margin_total` i `monthly_margin_pct` były dla DL
puste. Reguła została **wyniesiona do jednego miejsca** —
`can_read_client_finance` w `backend/app/api/financial_access.py` — i oba moduły
(`clients.py`, `my_clients.py`) wołają teraz tę samą funkcję.

**Potwierdzone testem, nie lekturą kodu.** Istniejący
`test_my_clients_dl_only_assigned` (prawdziwe HTTP + Postgres) asertował wprost
`"total_revenue_all_time" not in row` i `"monthly_margin_total" not in body` dla
Delivery Leada. Po zmianie ten test pada na pierwszej z tych asercji — czyli
zachowanie było realne i zakodowane, a zmiana trafia dokładnie w nie. Test
przepisano na nową regułę.

### Gdzie to naprawdę widać (i gdzie nie)

- **Widać w zakładce Analityka** profilu klienta (`/clients/{id}?tab=analityka`,
  komponent `AnalyticsTab`, zasilany przez `GET /api/my-clients/{id}/dashboard`):
  „Revenue lifetime", „Active revenue", „Marża/mc", „Revenue per waluta".
- **Nie widać na liście `/my-clients`** — `my-clients/page.tsx` ani
  `MyClientsTab.tsx` nie czytają `total_revenue_all_time` / `active_revenue`.
  Te pola nie mają dziś konsumenta w UI; objęte regułą dla spójności kontraktu
  API, nie dla efektu wizualnego.

### Front miał WŁASNĄ bramkę — sam backend by nie wystarczył

`AnalyticsTab` gasił kafle finansowe przez
`hasAnalyticsCapability(user, "view_finance")`, więc chowałby je przed DL nawet
po naprawie backendu. Zastąpione przez `canViewClientFinance(user, clientId)`
(`store/auth.ts`) — lustro reguły backendowej liczone z `data_scope`
z `GET /api/auth/me`, a więc z tego samego `resolve_dashboard_scope`, którego
używa backend. Świadomie **nie** z testu roli: hybryda HoR+DL ma zakres
`recruitment_org` i po obu stronach zostaje bez kwot.

### Testy części drugiej

`backend/tests/test_dl_portal.py`:

- `test_my_clients_dl_sees_money_of_own_portfolio` — lista i dashboard, kwoty co
  do grosza (25 000 przychodu, marża 3 000 = 15 000 − 12 000),
- `test_my_clients_dashboard_denies_dl_outside_the_portfolio` — 403 na obcym
  kliencie,
- `test_my_clients_hor_stays_without_money` — hybryda HoR+DL bez kwot na liście
  i na dashboardzie.

`frontend/src/components/AnalyticsTab.test.tsx` — DL u swojego klienta widzi
kafle; DL poza portfelem i hybryda HoR+DL ich nie widzą; ekran operacyjny
działa, gdy backend kwoty pominął.

**Dowód, że testy dotykają zepsutej ścieżki:** po cofnięciu poprawki backendu
`1 failed, 17 passed` (pada `test_my_clients_dl_sees_money_of_own_portfolio`);
po cofnięciu poprawki front-endu `1 failed | 5 passed` w
`AnalyticsTab.test.tsx`. Testy-zapory (403, hybryda HoR+DL) przechodzą w obie
strony — taka jest ich rola.

## Zauważone, NIE naprawione

Na produkcji `monthly_margin_pct` dla Nordei to **603,82%**:
`monthly_margin_total` (1 833 307 — suma marż MIESIĘCZNYCH z 283 kontraktów)
jest dzielona przez `active_revenue` (303 616 — suma `ClientOrder.total_value`
aktywnych zamówień). To dwie różne wielkości i ich iloraz nie znaczy nic. Defekt
zastany, niezależny od uprawnień — po tej zmianie zobaczy go po prostu więcej
osób.
