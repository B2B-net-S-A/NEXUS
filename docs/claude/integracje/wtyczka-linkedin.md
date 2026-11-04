# Wtyczka LinkedIn → NEXUS (panel boczny Chrome, 28.10.2026)
<!-- indeks: decyzje Artura 28.10, klucz nxe_ per osoba tylko na /api/extension/*, odczyt na kliknięcie, limit dzienny, off-limits jak w NEXUSIE, Web Store niepubliczna -->

Wtyczka Chrome dla zespołu na LinkedInie i w LinkedIn Recruiterze. Makiety
i decyzje: https://claude.ai/artifact/1PEmR5Gm5UQTdtRwVCRRg4. Kod: `extension/`
(kontrakt API: `extension/API.md`), backend `api/linkedin_extension.py`,
front `/extension/connect` i Ustawienia → Integracje → „Wtyczka LinkedIn”.
Stara wtyczka v0.2 (modal na stronie, logowanie hasłem) została usunięta.

## Decyzje Artura z 28.10.2026

- **Wszystko w jednym wydaniu:** profil (jest / nie ma w NEXUSIE), kto
  prowadzi, off-limits i kontraktor, dodanie do bazy i rekrutacji, szkic
  wiadomości z zapisem kontaktu, strona wyników i projekt w Recruiterze.
- **Dystrybucja: Chrome Web Store jako niepubliczna** (instalacja z linku,
  aktualizacje same). Id wtyczki ze sklepu wpisuje się do
  `LINKEDIN_EXTENSION_IDS` (workflow „Coolify set env”).
- **RODO art. 14 jak dziś** — wtyczka nie dopisuje zdania do wiadomości
  i nie liczy terminu informacji.
- **Tylko panel boczny** — do strony LinkedIna nic nie doklejamy (żadnych
  plakietek przy nazwiskach). Mniej widać nas dla LinkedIna i nic się nie
  psuje, gdy LinkedIn zmieni wygląd.

## Zasady, których nie cofać „przy okazji”

- **Odczyt tylko na akcję człowieka i tylko otwartej strony.** Żadnego
  przeglądania profili w tle, wywołań wewnętrznego API LinkedIna (voyager),
  automatycznych wiadomości ani zaproszeń. Regulamin LinkedIna zakazuje
  automatów, a konto Recruiter jest drogie. Szkic wiadomości rekruter kopiuje
  i wysyła sam.
- **Limit dzienny na osobę:** `LINKEDIN_EXTENSION_DAILY_READ_LIMIT` (150)
  odczytów stron — profil albo strona wyników = 1. Ponad limit 429
  `extension_daily_limit`.
- **Klucz `nxe_v1_…` per osoba**, nie JWT i nie konto serwisowe. Czyta go
  wyłącznie zależność `api/extension_deps.py` na trasach `/api/extension/*`;
  JWT na tych trasach daje 401, klucz na reszcie API też. Klucz niesie
  `authorization_version` z chwili połączenia — zmiana roli albo hasła odłącza
  wtyczkę. Nowe połączenie osoby odwołuje poprzednie. Admin odłącza w
  Ustawieniach. Kill-switch: `LINKEDIN_EXTENSION_ENABLED=false`.
- **Klucz trafia tylko do wtyczki z listy `LINKEDIN_EXTENSION_IDS`** (strona
  `/extension/connect` → `chrome.runtime.sendMessage`). Pusta lista = nikt nie
  połączy wtyczki; inaczej obca wtyczka w przeglądarce mogłaby odebrać klucz.
  Strona najpierw pinguje wtyczkę (`nexus-ping`) i bez odpowiedzi nie prosi
  o klucz — nowe połączenie odwołuje poprzednie.
- **Uprawnienia jak w NEXUSIE:** role `RecruiterPlus` i sufit sekcji Sourcing
  (odczyt dla sprawdzania, zapis dla dodawania), liczony w
  `ExtensionReader`/`ExtensionWriter`, bo `require_section_access` czyta JWT.
- **Zapisy tą samą drogą co w NEXUSIE:** `apply_candidate_create`,
  przypisanie do kolumny „Nowi” z bramką dopuszczalności, notatki przez
  `apply_note_create`. Off-limits pyta tak jak w NEXUSIE (409
  `off_limits_confirmation_required`, odpowiedź `off_limits_how` = klucz
  `HOW_LABELS` albo `skip`); osoba dodawana z LinkedIna nie ma jeszcze id,
  więc odpowiedź idzie w ciele żądania (`client_off_limits.add_confirmation`),
  a nie w nagłówku.
- **Rozpoznanie osoby:** link do profilu (`candidates.linkedin_slug`), potem
  imię i nazwisko ze zgodną firmą. Samo nazwisko bez firmy = „może to ta
  osoba” (`ambiguous`), nigdy pewne „jest w NEXUSIE”. Osoba o tym samym
  nazwisku z innym linkiem to ktoś inny.
- **Firma ze strony LinkedIna wygrywa** z naszymi danymi przy off-limits
  (jest świeższa); do NEXUSA trafia dopiero po „Zaktualizuj w NEXUSIE”.
- **Kontakt z wtyczki = notatka `contact_attempt`** z `source_ref =
  linkedin_extension:<kanał>`; przypomnienie to wydarzenie `deadline`
  w kalendarzu rekrutera (9:00 w N-tym dniu roboczym).
- **Dopasowanie do rekrutacji jest podpowiedzią** (Voyage + scoring jak
  podgląd CV); awaria daje pustą listę. Lista wyników nie liczy procentów
  (z listy jest tylko nagłówek, a to byłoby wywołanie Voyage na osobę).
- **Szkic wiadomości: F38 `linkedin_message_draft`** (rejestr
  `ai_models.py`, `ai_feature()`); bez modelu wtyczka dostaje szablon
  z rekrutacji (`ai: false`). Zaproszenie ≤ 300 znaków.
- **Awaria nie wygląda jak „Nie ma w NEXUSIE”** — panel pokazuje błąd
  połączenia, a pole, którego czytnik nie odczytał, oznacza „wpisz ręcznie”.

## Jak wtyczka czyta LinkedIna (pomiar 28.10.2026)

Nowy LinkedIn (2025/26) nie ma `h1`, klas `pvs-list`/`artdeco` ani `ul/li`
w sekcjach; klasy są haszowane. Czytniki pracują na `innerText` żywej strony:
imię = pierwszy `h2` w `main`, karta górna = jego `section`, sekcje po
nagłówkach `h2`, pozycje doświadczenia rozdzielone `hr` (lista = rodzic
dzielony przez najwięcej `hr`; pojedynczy płytszy `hr` to stopka „Show all”),
wyniki wyszukiwania = `[role=list] [role=listitem]`. Sekcje doładowują się
po przewinięciu kontenera strony (nie `window`). Sprawdzone na żywo: profil
i lista wyników. **Recruiter (`/talent/…`) został zmierzony na aktywnym koncie
28.10.2026**: trzy wiersze wyników oraz dwa układy profilu (panel boczny
i osobna strona profilu). Sprawdzono obecność imienia i nazwiska, nagłówka,
lokalizacji, pozycji doświadczenia i umiejętności.
Wersja 1.0.1 uwzględnia kontrolkę „Select …” przed imieniem w wierszu i panel
profilu poza główną sekcją strony z wynikami. Pomiary nie eksportują danych
rzeczywistych osób do repozytorium; regresje używają fikcyjnych fixture’ów.

Pomiar DOM Recruitera i lokalna instalacja ZIP-a nie zastępują pełnej ścieżki
zainstalowanej wtyczki z kontem rekrutera i produkcyjnym NEXUSEM. Ten etap
wymaga osobnego potwierdzenia po połączeniu wtyczki.

**Pomiar 02.11.2026 (1.0.4):** główna wyszukiwarka Recruitera to `/talent/search`,
a profil z niej to `/talent/search/profile/…`. Lista ma na starcie 3 z 25 wierszy,
reszta doładowuje się po przewinięciu strony. Wiersze nie mają linku `/in/`, więc
rozpoznanie osoby na liście idzie po imieniu i firmie; firma stoi w pierwszej
pozycji grupy „Experience” (`… at Firma · 2023 – Present`). Nadal poza panelem,
bo niezmierzone: `discover/automatedSourcing/review` i `discover/applicants`
bez otwartego profilu.

## Tryb pracy na requeście (decyzja Artura 02.11.2026, wersja 1.0.5)

Rekruter pyta, czy NEXUS może od razu łączyć aktywność na LinkedInie z konkretnym
requestem. Artur wybrał i zaakceptował makietę
https://claude.ai/artifact/4L1s92CaXHKYsbpQv7s5os: rekruter raz wybiera rekrutację na
pasku „Pracuję nad”, panel pamięta ją dla projektu Recruitera, a dodania i kontakty
domyślnie do niej trafiają. **Odrzucone:** odczyt skrzynki Recruitera i trzymanie wyboru
na serwerze. Odczyt i zapis nadal tylko na akcję człowieka.

- **Pamięć:** `chrome.storage.local`, `activeJobs[serwer][kontekst]`. Kontekst to
  `hire/<id>` z adresu projektu albo `global` poza projektem (`workContext`). Osobno na
  serwer, bo id ze stagingu nic nie znaczy na produkcji. Najwyżej 50 projektów na serwer.
  NEXUS nie zna powiązania projektu Recruitera z rekrutacją, więc w każdym projekcie
  wybiera się ją raz ręcznie.
- **Procent:** `/lookup` z `active_job_id` oddaje `active_job` z procentem także poniżej
  progu 50. Podobieństwo liczone do tej jednej rekrutacji (`job_ids` w
  `search_jobs_semantic`), bo poza czołówką 30 byłoby 0 i zaniżało wynik. Awaria
  dopasowania = `score: null`, nie 0% i nie błąd lookupu.
- **Zamknięta albo nieistniejąca rekrutacja** = `active_job: null`, bez błędu. Panel mówi
  o tym na pasku, czyści wybór i niczego nie zaznacza.
- **Limit odczytów:** zmiana wyboru na pasku przy odczytanym profilu nie czyta strony
  LinkedIna ani nie zużywa odczytu: panel woła `POST /active-job` z już odczytanym
  profilem, jak `/draft-message`. Prototyp robił tu pełny odczyt z przewijaniem i liczył
  1 z 150 przy każdym kliknięciu, a do tego kasował wpisane poprawki. Powrót na profil
  z pamięci panelu (10 min) z innym wyborem też idzie tą trasą. Odczyt liczy tylko
  faktyczne czytanie strony (`/lookup`, `/lookup-batch`).
- **Off-limits bez zmian:** zaznaczenie z paska nie omija pytania, bo `submit` wymaga
  odpowiedzi, a backend i tak zwraca 409. „Nie, to my” = bez rekrutacji, także tej z paska.
  Ramki off-limits i kontraktora stoją nad „Dodaj do tej rekrutacji”.
- **Lista:** nie ma już wyboru „Do:”, rekrutacja idzie z paska, a ekran mówi, dokąd trafią
  osoby. Procentów na liście nadal nie ma.
- **Pasek nie traci fokusu:** picker budujemy od nowa tylko po zmianie projektu albo wyboru
  spoza niego (`renderWorkbar`), reszta przerysowań dotyka widoczności i podpowiedzi.

Niezmierzone na żywym Recruiterze: czy profil otwierany z projektu ma w adresie
`/talent/hire/<id>/…/profile/…` w każdym układzie. Gdy otworzy się jako `/talent/profile/…`,
panel użyje wyboru spoza projektu.

**Pomiar 03.11.2026 (1.0.7):** kod z ZIP-a uruchomiony w zalogowanej karcie Recruitera
(lista wyszukiwania, lista w projekcie, trzy profile). Daty stanowisk Recruiter rozdziela
znakiem `•`, nie `·`, więc 1.0.6 gubiła daty zakończonych stanowisk, a z nimi staż
i odczyt doświadczenia. Sekcja „Summary” ma w `aria-hidden` tylko plakietki (`· 1st`)
i ułamki opisu, dlatego opis bierzemy z tekstu strony, gdy jest dłuższy. Zainstalowanego
panelu nie da się prowadzić z narzędzi: `chrome://` i `chrome-extension://` są dla nich
zablokowane, więc pełną ścieżkę na prawdziwym LinkedInie przechodzi człowiek.

## Dystrybucja: ZIP z NEXUSA i Web Store (29.10.2026)

Prośba Artura z 29.10: wtyczka ma działać u zespołu także wtedy, gdy Google nie
zaakceptuje jej w sklepie — ludzie instalują ZIP sami, a działa tylko z kontem
NEXUSA.

- **ZIP zespołu** `frontend/public/wtyczka/nexus-linkedin.zip`, strona
  `/wtyczka` (za logowaniem) z instrukcją „Wczytaj rozpakowane”. Manifest ma pole
  `key` → stałe id `pmnonjpommkjblgacmpaclgacjmipplm` na każdym laptopie; to id
  jest na `LINKEDIN_EXTENSION_IDS`. **Nie zmieniaj ani nie usuwaj `key`** — nowe
  id odetnie wszystkich do czasu zmiany env.
- **Paczka do sklepu** bez `key` (`pack.sh` usuwa pole), id sklepu
  `iaajabmhhcchodnkkgdffclgihdeipmo` też na liście.
- **Konto NEXUSA jest warunkiem:** ZIP sam nic nie robi (kod i tak jest w
  publicznym repo); połączenie wymaga zalogowania i roli z `RecruiterPlus`
  (z finansami, decyzja z 19.08), klucz działa tylko na `/api/extension/*`.
- **Aktualizacje:** ZIP się nie aktualizuje — panel pokazuje „Jest nowa wersja”
  (`latest_version` z `/me`). Wydanie: podbij wersję w 4 miejscach i `pack.sh`
  (`extension/README.md` → „Wydanie nowej wersji”); testy pilnują zgodności.
- **Laptopy firmowe przez Intune** (decyzja Artura 29.10): polityka Chrome
  `ExtensionInstallForcelist` z `update.xml` i `.crx` z `frontend/public/wtyczka/`,
  podpisanym kluczem z `key` tylko na laptopie Artura. Bez trybu dewelopera,
  aktualizacje same. Plan, warunki Chrome i kroki w Intune:
  `wtyczka-linkedin-intune.md`.

## Gdy LinkedIn zmieni stronę

Selektory czytników są w jednym pliku: `extension/src/readers/selectors.js`.
Poprawka = nowa wersja wtyczki: w sklepie aktualizuje się sama, z ZIP-a — po
banerze „Jest nowa wersja” w panelu. Testy
czytników działają na syntetycznych stronach (`node --test extension/test`) —
bez prawdziwych danych z LinkedIna w repo.
