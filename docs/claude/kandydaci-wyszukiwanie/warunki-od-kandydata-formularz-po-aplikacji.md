# Warunki od kandydata: mail po aplikacji i formularz „Twoje warunki” (17.11.2026)

<!-- indeks: candidate_terms, candidate_terms_requests, /warunki/<token>, kariera@, CANDIDATE_MAIL_SENDER_UPN, CANDIDATE_TERMS_DAILY_LIMIT, podziękowanie po aplikacji, stawka od kandydata, wypis z pytań -->

Decyzje Artura z 16 i 17.11.2026. Makiety: https://claude.ai/artifact/7eyYasRzy1WkXYvr7EGL5f,
analiza wysyłki i plan testów: https://claude.ai/artifact/BFWRPbbq7XaSufWkVoHRfS.
Pomiar na kopii z 15.11: 5 066 osób z ogłoszeń w 30 dni, 94% bez stawki i trybu,
96% bez dni w biurze, 100% bez miast.

## Reguła

- **Każdy aplikujący z ogłoszenia (Pracuj.pl, JustJoin.IT, RocketJobs) i ze strony
  kariery dostaje mail „Dziękujemy za zgłoszenie”.** Link do formularza warunków
  tylko wtedy, gdy profilowi brakuje choć jednego z: stawka, tryb pracy, biuro
  (dni przy hybrydzie, miasta przy hybrydzie albo biurze), start. Link najwyżej
  raz na 30 dni. Pozostali dostają samo podziękowanie.
- **Bez maila:** brak adresu, czarna lista, żywa umowa („pracuje u nas”),
  aplikacja starsza niż 3 dni (import zaległości). Reguły i kolejność:
  `services/candidate_terms.py::eligibility` (czysta funkcja, testy w
  `tests/test_candidate_terms.py`).
- **Zastępuje decyzję z 29.10.2026 „bez maili do kandydatów”**, ale rodzaj
  `candidate_terms` jest w `ADMIN_DECIDES` i startuje wyłączony. Admin włącza go
  w Ustawieniach → Powiadomienia dopiero po próbnym mailu (T3) i pilocie (T4).
  Włączony rodzaj wyłącza `application_confirmation` dla strony kariery, żeby
  kandydat nie dostał dwóch maili.
- **Nadawca:** osobna skrzynka `kariera@b2bnetwork.pl` (`CANDIDATE_MAIL_SENDER_UPN`,
  świadomy wyjątek od jednej skrzynki z 09.11). Pusta zmienna przy Graph = mail
  do kandydata nie wychodzi; skrzynka zespołowa nie pisze do kandydatów.
  Bezpiecznik Graph jest osobny dla tej skrzynki (`mail_circuit.sender_scope`).
- **Bez Reply-To i bez zachęty do odpowiedzi** (decyzja Artura 17.11.2026: „nie chcemy,
  żeby odpisywali na maile, tylko wypełniali formularz”). Stopka mówi „nie odpowiadaj”.
- **Format (etap 0, 18.11.2026):** mail z linkiem ma część tekstową obok HTML
  i nagłówki `List-Unsubscribe` + `List-Unsubscribe-Post: List-Unsubscribe=One-Click`
  wskazujące `POST {PUBLIC_API_BASE_URL}/api/public/candidate-terms/<token>/opt-out`
  (Gmail i Yahoo wymagają tego od nadawców masowych). JSON Graph przyjmuje tylko
  nagłówki `x-*`, więc taki mail idzie przez `sendMail` w MIME
  (`app_mail._mime_body`). Samo podziękowanie nie ma tokenu, więc nie ma nagłówka.
  Nie dawaj `mailto:` w wypisie: MX domeny wskazuje hosting, nie M365.
- **Wysyłka:** pętla `candidate_terms_sender` co 5 min, 8:00–20:00 Warszawa,
  limit `CANDIDATE_TERMS_DAILY_LIMIT` (400). Zgłoszenia sprzed włączenia rodzaju
  odpadają (`before_enabled`), nie ma zaległości. Na stagingu pętla zablokowana
  (`STAGING_BLOCKED_TASKS`); test: `process_queue` ręcznie, poczta w Mailpicie.
- **Kolejka:** `candidate_terms_requests` (0729, DDL w
  `services/candidate_terms_schema.py`). Zgłoszenie tylko dopisuje wiersz,
  decyzję podejmuje wysyłka. Jeden wiersz na osobę na dobę (import Pracuj.pl idzie
  ogólną trasą źródeł, JJIT trasą portalu, obie dla tej samej aplikacji).
  Wyzwalacze: `POST /candidates/{id}/sources` (kanał `posting`/`career_link_*`),
  `portal_application.place_application`, `public_apply`.
- **Token:** tworzony przy wysyłce, w bazie tylko SHA-256, ważny 14 dni, wiele
  zapisów. Otwarcie niczego nie zmienia (skanery linków w poczcie). Strona
  `/warunki/<token>` pokazuje tylko tytuł ogłoszenia i ostatnią odpowiedź
  kandydata, nigdy wartości z profilu. `?wypis=1` = „Nie chcę dostawać takich
  pytań” (działa po terminie).
- **Zapis do profilu** (`services/candidate_terms_apply.py`): odpowiedź nadpisuje
  profil, stara wartość zostaje w dzienniku. Stawka = jawne minimum
  (`update_candidate_profile_rate(meaning="minimum", source="candidate_terms")`,
  miesiąc ÷ 168 h, tylko PLN), tryb i dni przez `set_profile_work_mode`, miasta
  w `preferences.office_cities`, start w `availability_date`/`notice_period`.
  Pole zmienione przez człowieka w ostatnich 14 dniach zostaje (`details.kept`
  wpisu `candidate_terms_answered`). Zgoda na inne rekrutacje leży w odpowiedzi.

## Czego nie robić

- Nie wysyłaj tych maili ze skrzynki zespołowej (`M365_MAIL_SENDER_UPN`).
- Nie pokazuj na stronie formularza danych z profilu — link bywa przekazywany dalej.
- Nie dodawaj piksela śledzącego ani skracacza linków (dostarczalność).
- Nie włączaj rodzaju bez T3 (próbny mail na Gmail i skrzynkę firmową,
  nagłówki SPF/DKIM/DMARC = PASS) i T4 (pilot do 20 dziennie przez 5 dni).
