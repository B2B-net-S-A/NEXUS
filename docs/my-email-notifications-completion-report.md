# „Maile do Ciebie” — każdy widzi i sam ustawia swoje maile (09.10.2026)

## Skąd to zgłoszenie

Po wdrożeniu ekranu „Powiadomienia” (#2105) Artur zapytał: „dlaczego rekruter
nie widzi w ustawieniach powiadomień, jakie e-maile otrzymuje?”, a potem:
„zrób też tak, żeby każdy mógł sobie ustawiać, jakie e-maile do niego
przychodzą”.

Stan przed zmianą: lista maili stała tylko w zakładce „Maile”, którą widzi
administrator, i opisywała politykę całej firmy. W zakładce „Moje” konto bez
uprawnień administratora widziało kategorie dzwonka i jeden przełącznik —
poranny skrót. Nigdzie nie było odpowiedzi na pytanie „co przychodzi do mnie
mailem”.

## Decyzja Artura (09.10.2026)

Każdy mail da się wyłączyć sobie, także maile-zadania („CV czeka na Twój
przegląd”, prośba o podpis, wzrost stawki). Zadanie zostaje w dzwonku
i w „Czeka na Ciebie”, a administrator widzi, kto co wyłączył. Zawsze
przychodzą tylko maile bezpieczeństwa konta.

## Co weszło

**Zakładka „Moje” → „Maile do Ciebie”.** Wiersz na każdy mail, który może
trafić do konta: nazwa, kiedy wychodzi, przełącznik „tylko sobie”. Gdy mail
i tak nie przychodzi, wiersz mówi dlaczego: wyłączony dla całej firmy przez
administratora albo zatrzymany przez wyciszoną kategorię dzwonka (własną albo
wyłączoną dla roli). Pod listą: maile, które nie dotyczą roli konta, i zdanie
o mailach bezpieczeństwa konta.

**Kogo dotyczy który mail** (`services/notification_email_prefs.APPLIES`,
ustalone z kodu nadawców):

| Mail | Dotyczy konta, gdy |
|---|---|
| Poranny skrót | rekruter, TCM, Delivery Lead, Head of Recruitment albo Finanse + odczyt Pipeline |
| CV czeka na Twój przegląd | Delivery Lead albo bieżąca osoba od Cpro |
| CV wróciło do poprawy, zmiany etapów, terminy rekrutacji | dostęp do kandydatów + odczyt Pipeline |
| Wzmianki w notatkach | dostęp do kandydatów |
| Nowa rekrutacja dla Ciebie | rekruter, Delivery Lead albo admin |
| Prośba o potwierdzenie podpisu | uprawnienie „Podpis B2B” |
| Wzrost stawki po wysłaniu CV, alerty klientów i umów | Delivery Lead |
| Awaria automatu | admin |
| Nieprzeczytane wiadomości czatu | główna rola z dostępem do kandydatów, bez Finansów |
| Tygodniowy raport KPI | Head of Recruitment + odczyt Insights |
| Miesięczne podsumowanie Rady | „Moduł Finanse” + odczyt Insights |

**Egzekwowanie.** Każdy nadawca pyta `email_opted_out(konto, rodzaj)` tuż przed
wysyłką: kolejka maili natychmiast, czat, wzmianki, reguły etapów, zmiana
stawki, terminy rekrutacji, alerty klientów, raporty KPI. Poranny skrót
odsiewa konta własną kolumną w zapytaniu. Wyłączony mail nie rezerwuje wiersza
i nie zmienia dzwonka.

**Zakładka „Maile” (admin).** Przy rodzaju maila: „N osób wyłączyło sobie ten
mail” z nazwiskami po rozwinięciu.

**Dane.** `users.email_opt_outs` (migracja 0427 + lustro w `entrypoint.sh`).
Poranny skrót zostaje przy `users.daily_digest_email_enabled` (0425).

**Trasy.** `GET /api/users/me/email-notifications`,
`PUT /api/users/me/email-notifications/{kind}` — zawsze tylko własne konto.

## Poza zakresem

- Własne przełączniki dzwonka per grupa (zostają kategorie).
- Mail potwierdzenia aplikacji (idzie do kandydata) i maile bezpieczeństwa konta.
- Znalezione przy odczycie nadawców, bez zmiany:
  - tygodniowy raport KPI nie liczy wyjątków sekcji konta
    (`kpi_email_reports._recipients` nie woła `resolve_effective_access`);
  - po rezerwacji wiersza czat nie odświeża wyciszeń kategorii konta
    (kolejka maili natychmiast to robi);
  - prośba o potwierdzenie podpisu, gdy Delivery Lead rekrutacji jest aktywny,
    ale nie ma już roli DL, nie trafia do nikogo (`_dl_reviewers`).

## Weryfikacja

- Backend lokalnie (Python 3.12, bez bazy): `tests/test_notification_email_prefs.py`
  — reguły „kogo dotyczy”, stany wiersza, zapis, strażnik AST nadawców, lustro
  migracji; strażnicy tras (`test_route_authz_contract`,
  `test_section_ceiling_contract`, `test_authz_guard_matrix` z nowym wzorcem),
  stemple instrukcji zamówień, `ruff check` i `ruff format --check`.
- Backend z bazą (odczyt i zapis tras, lista „kto wyłączył” u admina): tylko
  w CI — na tym komputerze nie stawiamy Postgresa.
- Frontend: testy panelu „Moje”, zakładki „Maile”, ekranu i strażników
  harnessów (115 + 290 testów), `tsc --noEmit`, ESLint zmienionych plików.
- Przeglądarka, harness `/preview/notification-settings?as=recruiter` przy
  1280×720: pięć maili w czterech stanach, rozwinięte „nie dotyczą Twojej roli
  (3)”, nieudany zapis zostawia przełącznik i pokazuje błąd; 375 px bez
  poziomego przewijania. `?tab=maile`: „2 osoby wyłączyły sobie ten mail”
  z nazwiskami.
- Niepotwierdzone do wdrożenia: odczyt trasy na produkcji i pierwszy mail
  pominięty z powodu własnego wyłącznika.
