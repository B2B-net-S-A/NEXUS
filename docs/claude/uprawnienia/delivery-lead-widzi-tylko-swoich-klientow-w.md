# Delivery Lead widzi tylko swoich klientów w modułach Delivery (25.09.2026)

Decyzja Artura 25.09.2026 cofa org-wide odczyt z #1365 — ale tylko w Delivery.
DL widzi klienta, gdy ma DOWOLNY wiersz w `delivery_lead_client_assignments`
(główny albo nie — zastępstwo na urlop = dopisanie drugiego DL).

- **Jedno źródło:** `access_scope.resolve_delivery_lead_client_ids` (zakres
  Delivery) i `client_access.resolve_client_team_client_ids(..., purpose=)`
  (`"delivery"` domyślnie, fail-closed; `"org"` = wszyscy klienci). Przez nie
  zawężają się: Klienci (lista, katalog, profil, kontakty, wiedza, materiały,
  umowy ramowe/wykonawcze, reguły powiadomień), Kontrakty i kontraktorzy,
  Zamówienia, grupy i importy MD, skrzynka zamówień z maila, portal DL
  (`/my-clients`, `/my-clients/{id}/dashboard`), Kluczowe relacje, szablony
  umów, rejestr konfliktów per klient, kubełek klientów w wyszukiwarce.
- **Zostaje org-wide (świadomie):** rekrutacje (rekomendacje, prep-kit, szablony
  maili, akcje shortlisty — `resolve_delivery_lead_org_client_ids`), reguły CV
  i generator CV, zapis karty klienta, `GET /api/clients/{id}/team` (podpowiedź
  DL w formularzu rekrutacji), `/api/clients-lookup` (pickery klienta
  w rekrutacji), **Generator umów B2B** (`purpose="org"`; stawki i zapis nadal
  tylko u przypisanych — bez zmian), pulpity, KPI i Insights
  (`resolve_dashboard_scope` nietknięty).
- **Wyjątek od pulpitu: kontrakty i zamówienia w kreatorze metryk liczą tylko
  portfel DL** (decyzja Artura 26.09.2026, runda 6 audytu). Źródła `contracts`
  i `orders` (`custom_metrics/engine._delivery_client_boundary`, lustro warunków
  `resolve_delivery_lead_client_ids`) — także gotowe kafle „Aktywne kontrakty”
  i „Kończące się zamówienia”; klient spoza portfela w filtrze = 403
  `metric_scope_denied`, DL bez klientów = odmowa, nie zero.
- **Wyjątki persony:** DL + admin/finance/talent_community_manager widzi
  wszystko (TCM czyta Delivery całej organizacji).
- **Wyłącznik bez deployu:** `DL_CLIENT_SCOPE=all` przywraca stan z #1365.
  `/api/auth/me` niesie `delivery_client_scope` (`assigned|all|null`) — front
  chowa „Moi / Wszyscy” na liście klientów i na 403 profilu pisze „Ten klient
  jest poza Twoim portfelem”.
- **Nowa powierzchnia Delivery** = te resolvery. Nowa powierzchnia rekrutacji,
  która czyta klienta, = `purpose="org"` / `resolve_delivery_lead_org_client_ids`,
  inaczej DL straci ją u cudzych klientów. Pilnuje `tests/test_dl_client_scope.py`.
