# Delivery Lead widzi kwoty własnego portfela (profil klienta + Analityka)

Kwoty JEDNEGO klienta redaguje wspólna reguła **`can_read_client_finance`
(`api/financial_access.py`)**, a **nie** samo `VIEW_FINANCE`. Widzą: role z tą
capability (admin, finance) **oraz Delivery Lead — wyłącznie u klienta ze
swojego portfela**. Trzy powierzchnie:

| Powierzchnia | Endpoint | Co odsłania |
|---|---|---|
| Profil → Obecni konsultanci / Archiwum | `GET /api/clients/{id}/profile` | stawki, marża, MRR/LTV, widełki otwartych rekrutacji |
| Zakładka Analityka | `GET /api/my-clients/{id}/dashboard` | przychód lifetime/aktywny, marża/mc, revenue per waluta |
| Lista „Moi klienci" | `GET /api/my-clients` | `total_revenue_all_time`, `active_revenue` |

**Reguła mieszka w JEDNYM miejscu i tak ma zostać.** Rozjazd kopii kończy się
ekranem, który sam sobie przeczy: te same kwoty tego samego klienta widoczne
w jednej zakładce i puste w sąsiedniej.

- **Dlaczego wyjątek, a nie capability.** „Obecni konsultanci" to obsada DL,
  a stawka kosztowa/przychodowa i marża to trzy z pięciu kolumn tej tabeli —
  bez tego rola, dla której ta zakładka powstała, widziała w nich wyłącznie „—"
  (zgłoszenie 01.09). Dopisanie `VIEW_FINANCE` roli `delivery_lead`
  w `ROLE_CAPABILITIES` otworzyłoby razem z tym 40+ innych powierzchni
  (eksport kontraktów, przychody w `/my-clients`, `/settings/clients-overview`,
  dashboardy zarządcze). To ten sam kompromis co `_can_see_finance` w module
  zamówień: wąska powierzchnia zamiast szerokiej capability.
- **Granicą jest portfel, nie rola.** `client_id` musi leżeć
  w `resolve_delivery_lead_client_ids(user)`. Trasy i tak odcinają obcego klienta
  (`assert_delivery_lead_client_visible` / `require_dl_assigned_or_admin` → 403),
  ale finanse nie mogą wisieć na tym, że wcześniejsza linijka nie rzuciła wyjątku.
- **Na LIŚCIE granicy nie sprawdza się per wiersz, tylko per gałąź.**
  `list_my_clients` ma dwie: organizacyjną (admin/finance/TCM — WSZYSCY klienci)
  i DL-ową (filtr po własnych przypisaniach). Flaga
  `rows_are_callers_own_portfolio` ustawiana w obu gałęziach jest tym, co wiąże
  kwoty z zakresem wierszy. Sam `has_role(delivery_lead)` rozdałby hybrydzie
  HoR+DL przychody całej firmy, bo ta wchodzi gałęzią organizacyjną.
- **`None` jako granica = brak finansów z tej ścieżki.** Tak wygląda odbiorca
  nierządzony personą DL: admin (i tak ma capability) i rola nie-DL.
  **Hybryda `head_of_recruitment + delivery_lead` widzi kwoty WYŁĄCZNIE swojego
  portfela DL** (rolą Delivery Lead, nie nadzorem HoR) — tak liczy kod i front
  (audyt 24.09.2026; wcześniejszy opis „zostaje zredagowana” był nieaktualny).
  Pilnuje tego `test_head_of_recruitment_with_dl_role_sees_rates_only_in_dl_portfolio`
  i `test_my_clients_hor_with_dl_role_gets_scoped_delivery_money`.
- **`tac` i `head_of_recruitment` ZOSTAJĄ zredagowane i to nie jest przeoczenie**
  — TAC jest w zespole klienta i widzi konsultantów, ale obsady nie prowadzi
  (lustro decyzji z `_can_see_finance`); HoR przechodzi guardy klienta globalnie,
  bez przypisania. Macierz: `tests/test_client_access_matrix.py` (`financials`).
- **Redakcja jest całościowa albo żadna.** Częściowa rozjeżdża ten ekran ze sobą
  samym: kafel „Aktywne MRR" jest sumą kolumny „Marża" pod nim, a „Archiwum
  konsultantów" ma DOKŁADNIE te same trzy kolumny co zakładka obok.
- **Marża = przychodowa − kosztowa, po przewalutowaniu obu nóg na PLN osobno**
  (`_finance_rates_in_pln`), nigdy z kolumny `contracts.margin` — ta niesie
  kwotę z ostatniego ZAPISU kontraktu. `None` zostaje tylko wtedy, gdy brakuje
  danych źródłowych: stawki albo kursu FX dla waluty obcej.
- **Ekrany rekrutacji też nie pokazują DL-owi kwot cudzych klientów**
  (decyzja Artura 26.09.2026, runda 6 audytu). Historia requestów
  i baner podglądu (`jobs._history_fee_visible`) redagują `fee_rate` (marżę)
  per klient regułą `can_read_client_finance` — lista zostaje org-wide, także
  z `cross_client=true`, kwoty tylko portfela (hybryda HoR+DL też).
  Off-limits na karcie klienta: funkcja usunięta 27.09.2026 decyzją Artura;
  kolumny zostają.
- **Tabela konsultantów nie ma bramki front-endowej i mieć nie powinna** —
  `ConsultantsTable` rysuje wszystkie kolumny zawsze, a `null` renderuje jako
  „—". Decyduje wyłącznie backend.
- **Zakładka Analityka ma DRUGĄ bramkę, po stronie front-endu** — i o niej łatwo
  zapomnieć. `AnalyticsTab` sam decyduje, czy w ogóle wyrenderować kafle
  finansowe; przy samym `hasAnalyticsCapability(user, "view_finance")` chowała je
  przed DL nawet wtedy, gdy backend przysyłał już komplet liczb. Teraz woła
  `canViewClientFinance(user, clientId)` (`store/auth.ts`) — lustro reguły
  backendowej, liczone z `data_scope` z `GET /api/auth/me`, czyli z **tego
  samego** `resolve_dashboard_scope`, którego używa backend. Nie z roli:
  hybryda HoR+DL dostaje `recruitment_org` i kwot nie widzi po obu stronach.
- **Kwoty na LIŚCIE `/api/my-clients` nie mają dziś konsumenta w UI** —
  `MyClientsTab.tsx` czyta tylko pola operacyjne (`/my-clients` to od
  22.09.2026 przekierowanie na `/clients?mine=1`).
  Reguła obejmuje je dla spójności kontraktu API; nie szukaj tam efektu wizualnego.
  Efekt widać w zakładce **Analityka** profilu klienta.
