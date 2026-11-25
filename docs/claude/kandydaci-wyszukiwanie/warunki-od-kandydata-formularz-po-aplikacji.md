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
  MIME serializuj z `policy.SMTP.clone(max_line_length=998)`: przy domyślnych 78
  znakach adres wypisu z tokenem wychodził jako `=?utf-8?q?...?=` i Gmail go nie
  uznawał (T3 18.11.2026: dostarczenie i SPF/DKIM/DMARC = PASS, nagłówek zakodowany,
  `List-Unsubscribe-Post` nie dotarł).
- **Wygląd „Pasek postępu” (decyzja Artura 18.11.2026, makiety
  https://claude.ai/artifact/CqKhX41iCPVCwQJyam4ruR):** nagłówek z logo i stanowiskiem,
  „30 sekund.” i pasek z trzech odcinków (Zgłoszenie ✓, CV ✓, Twoje warunki), zdanie
  z tematami formularza zamiast wypunktowania, przycisk „Dokończ w 30 sekund”. Wypis,
  informacja o danych i dane spółki są na końcu i nic pod nimi nie stoi (logo tylko
  w nagłówku), bo Gmail zwija powtarzającą się stopkę w drugim mailu wątku. Ciemny
  wygląd przez `prefers-color-scheme` z jasnym logo. Samo podziękowanie nie ma paska
  ani „30 sekund”. Artur odrzucił listę pięciu tematów w mailu: zostaje jedno zdanie.
- **Ekrany `/warunki/<token>` w tym samym wyglądzie (decyzja Artura 19.11.2026,
  makiety https://claude.ai/artifact/TZhPRcvtxRWCLLVGC4w6jm):** jedna kolumna jak
  mail, karta z paskiem (trzeci odcinek wypełnia się z odpowiedziami, do pełna po
  zapisie), „Ostatni krok.” i „30 sekund” jak w mailu, po zapisie „Komplet.”,
  grafitowy przycisk, jasna stopka, ciemny tryb. Wygasły link mówi tylko, że
  zgłoszenie z CV nadal jest u nas: bez obietnicy nowego linku (wysyłka najwyżej
  raz na 30 dni i tylko przy brakach) i bez przycisku do ofert.
- **Kolory wariantu 5 „Czerwień w gradientach tech” (decyzja Artura 25.11.2026,
  jak strona główna i strona kariery #4009):** mail, `/warunki/<token>` i mail
  potwierdzenia biorą czerwień `#C42329`, tekst czerwony `#B0222A`,
  burgund-obsydian `#1F1115` zamiast grafitu (przycisk, tekst), tło `#F4EAE8`,
  linie `#E6D6D3`. W mailu bez gradientów (Outlook ich nie rysuje). Ciemny tryb:
  tło `#1F1115`, karta `#2E1A1F`, czerwień `#D43424` (`#C42329` miałaby tam
  2,82:1), linki i drobny czerwony tekst morelowe `#FFD6C9`. Limonki nie ma.
  Każda para tekst/tło ma co najmniej WCAG AA; nowy kolor = policz kontrast.
- **Bez zgody na inne rekrutacje** (decyzja Artura 19.11.2026: „i tak będziemy
  dzwonić z czymś innym, ale nie pisz tego i nie zbieraj zgody”). Formularz nie ma
  pola zgody i nie wysyła `future_consent`; backend dalej przyjmuje to pole jako
  opcjonalne ze starych odpowiedzi.
- **Wypis jednym kliknięciem w M365 zostaje bez dalszych prób** (decyzja Artura
  19.11.2026). T3b/T3c: `List-Unsubscribe-Post` nie dociera, a DKIM Microsoftu nie
  obejmuje nagłówków wypisu. Wymóg Gmaila i Yahoo dotyczy nadawców powyżej 5000
  maili dziennie; przy pilocie 20 dziennie wystarcza widoczny link „Wypisz się”
  i nagłówek `List-Unsubscribe`. Nie wracaj do reguł transportu ani innego kanału
  bez nowego faktu (np. skok wolumenu albo skargi na spam).
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
  wpisu `candidate_terms_answered`). Stare odpowiedzi mogą mieć `future_consent`; nowe go nie mają.

## Czego nie robić

- Nie wysyłaj tych maili ze skrzynki zespołowej (`M365_MAIL_SENDER_UPN`).
- Nie pokazuj na stronie formularza danych z profilu — link bywa przekazywany dalej.
- Nie dodawaj piksela śledzącego ani skracacza linków (dostarczalność).
- Próbny mail (T3): Coolify Ops → `candidate-terms-mail-probe` (`.github/scripts/candidate_terms_mail_probe.py`),
  stan skrzynki i uprawnień: `docs/m365-system-mail-setup.md`.
- Nie dodawaj do formularza zgody na inne rekrutacje.
- Nie włączaj rodzaju bez T3 (próbny mail na Gmail i skrzynkę firmową,
  nagłówki SPF/DKIM/DMARC = PASS) i T4 (pilot do 20 dziennie przez 5 dni). T4 dopiero po wdrożeniu ekranów z 19.11 i obejrzeniu próbnego maila na telefonie (decyzja Artura 19.11.2026).
- Nie wracaj do kolejności „najstarsze najpierw” w `process_queue`. Przy limicie 20 i około 270
  zgłoszeniach dziennie mail „Zgłoszenie przyjęte” szedłby 2–3 dni po aplikacji (pomiar 22.11.2026).
  Idą najnowsze, starsze odpadają po 3 dniach (decyzja Artura 22.11.2026).
