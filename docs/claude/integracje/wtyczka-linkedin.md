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
- **Opcja na później:** laptopy firmowe przez politykę Chrome
  (`ExtensionInstallForcelist`, własny `update.xml` + `.crx` podpisany kluczem
  z `key`) — bez trybu dewelopera i z automatycznymi aktualizacjami. Wymaga
  decyzji Artura i zarządzania Chrome przez Intune.

## Gdy LinkedIn zmieni stronę

Selektory czytników są w jednym pliku: `extension/src/readers/selectors.js`.
Poprawka = nowa wersja wtyczki: w sklepie aktualizuje się sama, z ZIP-a — po
banerze „Jest nowa wersja” w panelu. Testy
czytników działają na syntetycznych stronach (`node --test extension/test`) —
bez prawdziwych danych z LinkedIna w repo.
