# Rola `finance` = pełny odczyt biznesowy (decyzje Artura 19.08 i 31.08)

Rola `finance` ma organizacyjny odczyt wszystkich danych biznesowych: kandydatów,
rekrutacji i pipeline'u, klientów wraz z kontaktami/notatkami/materiałami i
dokumentami prawnymi, kontraktów/stawek/zamówień/wykonawców, Insights,
raportów, eksportów i czatów audytowych. Zakres nie zależy od membershipu
oferty, przypisania klienta ani `allowed_sections` (DynaReporter i Cortex
usunięte 23.09.2026 — `users.allowed_sections` zostaje w bazie bez konsumenta
tras).

**Odczyt nie nadaje prawa zapisu.** Nowe powierzchnie Finance muszą używać
dedykowanych read dependencies i read-scope helpers, nigdy globalnego dopisania
roli do `AdminUser`, `DeliveryLeadPlus`, membership command guardów ani mutacji domenowych.
Istniejące przed decyzją 31.08 operacyjne prawa Finance (m.in. tier
`RecruiterPlus`, akcje kandydackie/kalendarzowe i lifecycle zamówień) pozostają
bez zmian; ten kontrakt nie może ich po cichu odebrać. Mutacje techniczne
(użytkownicy/role/konfiguracja/backfille) pozostają Admin-only (kuratela
słownika umiejętności: admin + HoR), a zapisy finansowe nadal wymagają właściwej capability
`manage_finance`/`approve_finance`.

Wyłączność konta Finance (CHECK `ck_users_exclusive_finance_viewer_roles`) i
bramka własnego modułu Finanse pozostają bez zmian. Historyczne komentarze o
„finance-safe", person-free projections albo Finance „jak recruiter" opisują
stan sprzed decyzji 31.08 i nie są źródłem polityki.
