# Strona kariery dla kandydatów (kariera.b2bnetwork.pl, 0339, 22.09.2026)

Publiczny landing, który rekruterzy wrzucają na LinkedIna. Raport:
`docs/career-landing-completion-report.md`. Dwa rodzaje linku w
`candidate_invite_links` (`kind`):
- **`job`** — `/r/<slug>`: opis publiczny rekrutacji + formularz; kandydat
  trafia na etap „Nowy” tej rekrutacji po przeglądzie AI (0404 — sekcja
  „Zgłoszenia z linku rekrutacji przegląda AI” wyżej). Domyślnie **bez terminu** — ważny, póki
  rekrutacja jest otwarta (zamknięta = strona „proces zakończony” z listą
  innych otwartych rekrutacji osoby i odesłaniem do jej stałego linku, gdy go
  ma; stare `/apply/{token}` też dają wtedy 404).
- **`recruiter`** — `/<slug>` (np. `/marta-n`): stały link do bazy, jeden
  aktywny na osobę (częściowy UNIQUE). Bez rekrutacji: brak `open_process`,
  `CandidateSourceEvent.job_id = NULL`, osoba **przypięta w „Moich ludziach”**
  właściciela linku (`my_people` nie czyta `created_by`).

Reguły, które łatwo cofnąć:
- **Na stronę trafia wyłącznie zatwierdzony opis publiczny**
  (`job_public_profiles`, status liczony z hasha treści — edycja po zatwierdzeniu
  = szkic). Opis nigdy niezatwierdzony = 404. Publiczne GET-y budują odpowiedź z
  białej listy (`services/job_public_profile.py`): **nigdy klient, stawka,
  budżet ani nazwisko rekrutera** (tylko imię). Pilnuje test kształtu odpowiedzi.
- **Poprawka po zatwierdzeniu nie zdejmuje strony** (etap 1 linków, 19.10.2026,
  makiety https://claude.ai/artifact/8aVZkzVxkVnkVVNBUDgL4h). Kandydat widzi
  ostatnią zatwierdzoną wersję, dopóki nikt nie zatwierdzi nowej — wcześniej
  każda zmiana dawała 404 pod rozesłanym linkiem. Jedna reguła „co widzi
  kandydat” to `jpp.published_version` (strona, lista rekrutera, oba
  formularze, mail potwierdzenia); nie wracaj do `status == approved` w tych
  miejscach. Tekst wersji zatwierdzonej leży w migawce zatwierdzenia
  (`_approved_content.text`), ważny tylko gdy jego skrót równa się
  `approved_hash`. Opisy sprzed tej daty dostają tekst w migawce przy
  pierwszym zapisie zmian. Zmiana klienta rekrutacji nadal zdejmuje stronę
  (R8-N4-4). Zamknięta rekrutacja z opisem kiedyś zatwierdzonym zawsze daje
  „proces zakończony”. Edytor dostaje `live` (wersja widoczna dla kandydata,
  `pending_changes`), a „Odrzuć zmiany” zapisuje szkic z wartościami `live`.
  Portale (`job_portals.build_content`) nadal wymagają opisu zatwierdzonego
  w całości — ogłoszenia nie dostają wersji z migawki.
- **Tytuł domyślny bez kodów klienta** (19.10.2026): `default_public_title`
  zdejmuje `client_reference` w dowolnym miejscu, `RITM…`/`REQ…` także po „_”
  (BNP „Software Developer_RITM0866775” szło na stronę, do grafiki OG i do
  adresu linku) i `_PKN…`/`_EITE…`; nawias zdejmuje tylko z numerem albo kodem
  (`(42835)`, `(ZOB-3003)`), „(K8s)” i „(ISO 27001)” zostają — jak w nagłówku
  CV. Opis zatwierdzony z tytułem według dawnych reguł zostaje na stronie z tym
  tytułem (`legacy_default_public_title`), aż ktoś zatwierdzi nowy.
- **Kontrola kodów wewnętrznych** (`lint_internal_codes`, kod `internal_code`):
  `RITM|REQ|SCTASK|ZOB|PKN|EITE` z co najmniej 4 cyframi i części
  `client_reference` (od 4 znaków). Czyta ją tylko `lint_payload` (opis
  i tytuł), NIE kontrola adresu — znalezisko w adresie wymieniłoby rozesłany
  link (stary daje 404), a numer w adresie to kosmetyka.
- **Plakat z kodem QR** (etap 3, 19.10.2026): `GET /api/jobs/{id}/public-profile/poster.pdf`
  (`services/career_poster.py`, kod QR z `segno` jako `data:` SVG, PDF przez
  WeasyPrint z blokadą zasobów spoza `data:`). Treść wyłącznie z
  `published_version` (tytuł, podtytuł, parametry, do 3 wymagań — bez opisu
  projektu), adres = link osoby albo najnowszy aktywny link rekrutacji. 409,
  gdy strona nie działa albo rekrutacja jest zamknięta. Kanałów udostępniania
  NIE rozróżniamy (decyzja Artura 19.10.2026) — QR prowadzi na ten sam adres.
- **Wyniki linków** (etap 4, decyzja B Artura 19.10.2026): źródło zgłoszeń to
  `activities.applied_via_invite` (`user_id` = właściciel linku,
  `details.invite_token_sha256`, `was_duplicate`) — liczą się też osoby, które
  były już w bazie. Zakładka „Wyniki” w oknie (`GET /api/me/career-link/results?days=30|90|0`,
  `services/career_link_results.py`): lejek zgłoszenia → w rekrutacji →
  zweryfikowani → CV wysłane → zatrudnieni; etap liczy się, gdy osoba trafiła na
  niego PO zgłoszeniu w rekrutacji linku (link ogólny: w dowolnej). Kolumna
  „Z linków” w aktywności zespołu (`insights_team_activity`, unikalne osoby
  w oknie) jest POZA „Razem” — Liga, Cele i kredyt weryfikującego bez zmian.
  Wejścia to `visit_count` od początku istnienia linku (dat wejść nie
  zapisujemy) — w oknie „Mój link ogólny” podpisane „Wejścia od początku”.
- **Okno „Udostępnij”**: „Kopiuj” i „Otwórz stronę” dopiero, gdy strona działa
  (`live`); wcześniej link można wygenerować, ale nie trafia do schowka
  (kandydat dostałby 404, a LinkedIn zapamiętałby pusty podgląd). Zatwierdzony
  i niezmieniony opis = przycisk „Skopiuj link” bez ponownego zatwierdzenia.
  Kontrola świeci na zielono tylko dla treści sprawdzonej przez serwer; puste
  albo niezapisane pola = szare „sprawdzę po zapisaniu”. Znalezisko serwera
  znika z listy wyłącznie wtedy, gdy jego fragment usunięto z pól okna
  (`liveFindings` z `savedText`) — fragment z wymagań, tytułu domyślnego albo
  zdania skróconego wielokropkiem zostaje.
- **Kontrola przed publikacją jest deterministyczna**
  (`services/public_profile_lint.py`): nazwa i aliasy klienta, kwoty, kontakty,
  nazwiska. `approve` odmawia 422 `PUBLIC_PROFILE_FINDINGS`. Szkic AI
  (`AIFeatureKey.job_public_description`, Sonnet 5) jest tylko podpowiedzią —
  nie zapisuje się sam i nie omija kontroli. Kontrola skanuje też tytuł
  rekrutacji: klient w tytule blokuje publikację.
- **Kontrola ma jedno źródło ze sprawdzaniem ogłoszeń na portale**
  (`services/job_ad/lint.py` woła `lint_public_texts`; 13.10.2026). Nową
  regułę dopisuj w `public_profile_lint.py`, nie w kopii — kopia w ogłoszeniu
  miała już raz węższy wzorzec kwoty niż oryginał. Od tej daty kontrola łapie
  też:
  - kwoty słownie i bez symbolu waluty: „200 złotych”, „150 dolarów”,
    „3000 CZK”, „2 mln PLN”, „30 tys. netto”, „180 netto/h”, „15 000 brutto”;
  - „30 tys. PLN” — skróty „tys.”, „godz.” i „mies.” nie kończą zdania nawet
    przed wielką literą; cięcie po „tys.” chowało najzwyklejszy zapis kwoty;
  - linki (`http://`, `https://`, `www.`), e-mail zapisany jako
    „jan [at] firma” / „jan(at)firma(dot)pl”, telefon stacjonarny
    („22 555 12 34”) i z numerem kierunkowym („+48 22 555 12 34”);
  - tekst ze znakami, których nie widać (miękki łącznik, spacja zerowej
    szerokości, selektory wariantu, wypełniacze hangul) i znakami pełnej
    szerokości — porównanie idzie po `for_lint`, więc nazwa klienta z miękkim
    łącznikiem w środku nadal jest nazwą klienta.
- **Od 14.10.2026 (audyt 13.10.2026) kontrola łapie też** zapisy, które
  przechodziły: „180,- zł”, „180,-zł”, „180.- PLN” (kreska tylko po
  przecinku albo kropce — „5-osobowy” i „2.0-RC” kwotą nie są), „30 tyś. zł”,
  „30tyś PLN”, „30 tyś. netto” („tyś.” nie kończy zdania, jak „tys.”) oraz
  liczbę przy słowach „pensja” i „zarobki” (obok „budżet”, „widełki”,
  „wynagrodzenie”, „salary”, „stawka”, „rate”). Słowa o wynagrodzeniu
  (bez „stawka”/„rate”) siedzą w osobnym `PAY_WORD_MONEY_PATTERN`, bo
  ogłoszenie na portale blokuje je, a liczbę przy „stawka”/„rate” tylko
  zgłasza jako uwagę (decyzja Artura „A”).
- **Zapis opisu wycina znaki formatujące** (kategoria Cf, jak
  `job_ad/text.visible`; `api/career_links.put_public_profile`: tytuł,
  podtytuł, opis). „\u202ełz 081\u202c” przeglądarka pokazuje jako
  „180 zł”, a kontrola porównuje tekst bez tych znaków i widziała „łz 081”.
  Po zapisie strona pokazuje to, co czyta kontrola. Opisy zapisane przed
  14.10.2026 nie są czyszczone wstecz — przejdą przez to przy następnym
  zapisie. Ponowny zapis opisu, który miał np. miękki łącznik, zmienia
  skrót treści i zatwierdzony opis wraca do szkicu.
- **Wzorce są zawężone tam, gdzie łapały zwykły tekst** (przegląd
  13.10.2026) — nie poszerzaj ich bez przykładu z prawdziwego opisu:
  - „[at]”/„(at)” tylko małymi literami („Austria (AT) i Szwajcaria (CH)”
    to kody krajów);
  - „złoty” tylko w formach waluty („złotych”, „złote”, „złoty”) — „00-120
    Złota 59” to adres, a „zlot” bez „ł” to także zjazd;
  - liczba przed „netto/brutto” nie może być samym rokiem ani jedną cyfrą
    („przepisy 2024 brutto/netto”, „wersja 2 brutto/netto”);
  - adres bez „http” i „www” („firma.pl”) NIE jest regułą: końcówki „.net”,
    „.io”, „.js” to nazwy technologii, a strona kariery nie ma poziomu
    „uwaga” — każde znalezisko odmawia zatwierdzenia.
- **Czego kontrola nadal nie łapie** (sprawdzone 13.10.2026, nie obiecuj
  więcej): kwoty w całości słownie („dwieście złotych”), waluty oddzielonej
  od liczby słowem albo nową linią („180 w PLN”, „200⏎złotych”), kwoty bez
  waluty i bez słowa „stawka” („15 000 na rękę”, „90/hr”), walut spoza listy
  (SEK, RON, CAD…), adresów bez „http”/„www” („bit.ly/…”), linków pisanych
  „hxxps://” albo „www[.]x”, telefonów z kropkami, ukośnikami albo w innych
  grupach („600.100.200”, „22 555 1234”), e-maila „jan at firma dot pl”,
  liter z innego alfabetu podstawionych w nazwie klienta i nazw odmienionych
  (te łapie dopiero alias klienta).
- **Liczba we wzorcu kwoty nie startuje ze środka ciągu cyfr** (`_RUN_START`).
  NFKC wydłuża tekst („⒛” to „20.”), a wzorzec próbowany od każdej cyfry
  długiego ciągu liczył się kwadratowo — 4000 takich znaków dawało ponad
  2 s. Strażnik nie zmienia wyników: pilnuje tego test na 20 tys. losowych
  ciągów (`test_amount_start_guard_does_not_change_what_matches`), który
  złapał pierwszą, za szeroką wersję („ok.180 zł” przestawało być kwotą).
- **Kontrola sluga czyta część z tytułu, nie losową końcówkę.**
  `slug_findings` puszcza przez tę samą kontrolę adres `/r/<slug>`, a przy
  zatwierdzeniu opisu adres ze znaleziskiem jest WYMIENIANY (stary daje 404,
  `rotate_unsafe_job_slugs`). Końcówkę z czterech losowych znaków dopisujemy
  sami i potrafi wyglądać jak kwota: „…-zl1v” trafiało we wzorzec od
  początku istnienia kontroli (raz na ok. 1800 linków), „…-1czk” w nowy.
  Dlatego wymiana czyta `career_slugs.job_slug_content(slug)`. Nowa reguła
  nadal nie może pasować do części z tytułu („tester-22-555-12-34”): numer
  stacjonarny nie może stać po cyfrze ani łączniku.
- **Zaostrzenie kontroli nie zdejmuje opublikowanych stron.** Kontrola biegnie
  w podglądzie edytora i przy `approve`; opublikowany opis zostaje, dopóki
  ktoś go nie zmieni — dopiero ponowne zatwierdzenie przejdzie przez nowe
  reguły.
- **Zgoda jest wymagana na OBU formularzach** (nowym i starym `/apply/{token}`),
  zapis w `candidate_consents` w tej samej transakcji (tekst + wersja + sha256,
  `services/career_consent.py`; administrator B2B.NET S.A.). Zmiana treści zgody
  = nowa wersja, nigdy edycja w miejscu. FK CASCADE z kandydatem i ze zgłoszeniem
  (art. 17 RODO).
- **Dwie zgody od 19.10.2026 (decyzja D, wersja `2026-10-19`, 0477):**
  obowiązkowa `consent` → wiersz `recruitment_current` (ta rekrutacja),
  dobrowolna `consent_future` → wiersz `recruitment_future` (przyszłe
  rekrutacje), tylko gdy zaznaczona. Wiersze `recruitment_current_future`
  (jedna zgoda na oba cele, wersje do `2026-09-26`) zostają i liczą się jako
  zgoda na przyszłe; ich treść leży w `LEGACY_CONSENT_TEXT_2026_09_26`, a test
  pilnuje, że skrót się nie zmienił. Treść obu zgód i pkt 3 klauzuli `/rodo`
  zatwierdził Artur 19.10.2026 (pkt 5 — okres przechowywania — bez zmian).
  **Na dziś zgód nikt nie czyta**: wyszukiwanie, propozycje, automaty i
  „Talent Radar” nie odróżniają osoby bez zgody na przyszłe. Brak tej zgody ma
  znaczyć: po zamknięciu procesu osoba nie trafia do wyszukiwania ani
  propozycji — to osobne zadanie (przy duplikacie e-maila zgoda wisi na
  `application_submissions`, nie na kandydacie).
- **Strona kandydata (etap 5, 19.10.2026):** kroki procesu widoczne na każdej
  szerokości (poniżej 1024 px zwarta lista; manifest dalej tylko od 1024 px).
  Kolory w jednym miejscu: `components/career/palette.ts` (`OG_COLORS`) dla
  grafik OG i `LinkedInPreviewCard`, te same wartości jako `--kr-*` w
  `career.css` (test `palette.test.ts`). Bordo `#9A142D` ma na czarnym 2,5:1 —
  tylko tło pod białym tekstem i ozdobniki; czerwony w tekście tytułów to
  `title` `#F06A80` (≈7:1), drobny akcent `red` `#D14A5F` (≈4,9:1). Ekran
  zamkniętej rekrutacji dostaje z API `other_jobs` (ta sama reguła co stały
  link: opublikowany opis + „pokazuj na mojej stronie”) — bez listy i bez
  stałego linku prosi o kontakt z osobą od linku, nie odsyła na LinkedIna.
- **Szablony graficzne (0478, decyzje Artura 19.10.2026, makiety
  https://claude.ai/artifact/TFqDt54DUg4qRdyJXnu6wm):** 12 szablonów pod
  najczęściej rekrutowane role (zestawienie 12 mies.: testerzy, analityk
  systemowy, data, architekt, PM, Java, DevOps, analityk biznesowy, frontend,
  security, administrator). Wybór rekrutera w `job_public_profiles.theme`
  (NULL = domyślny), zapis samym `PUT …/public-profile {theme}` — **poza
  skrótem treści**, więc zmiana wyglądu nie cofa zatwierdzenia. Domyślny:
  rola z TYTUŁU (`services/career_theme.role_theme`), potem kategoria
  kompetencji, potem Terminal — sama kategoria nie wystarcza, bo analitycy
  i testerzy siedzą też w Infra i Management. Stare linki bez wyboru od razu
  dostają szablon swojej roli. Jedno źródło kolorów strony, grafiki OG
  i podglądu posta: `components/career/themes.ts` (lista id = `THEME_LABELS`
  w backendzie, pilnuje `themes.test.ts`); plakat: `career_theme.POSTER_COLORS`.
  Terminal nie dostaje owijki — dzisiejszy wygląd bez zmian. Kolory w
  `career.css` tylko przez `--kr-*` (test). Wynik interakcji „x z 5” (kolejne
  PR-y) zostaje w przeglądarce kandydata — nic nie wysyłamy (decyzja).
  Harness: `/preview/kariera?szablon=<id>`.
- **Jedna ścieżka zapisu zgłoszenia:** `services/public_apply.submit_application`
  (stary i nowy endpoint). Duplikat e-maila (od 22.09.2026, decyzja Artura —
  kolejka `/applications` przez całe życie nie dostała ani jednego wpisu) NIE
  czeka na decyzję: pola profilu nietknięte (P0-CAND-01), CV dochodzi jako
  dodatkowy, NIE główny dokument, link rekrutacji otwiera proces „Nowy”,
  stały link przypina w „Moich ludziach”; globalna czarna lista = sam
  dokument, bez procesu. `ApplicationSubmission` zostaje jako zapis
  (`linked`, zgoda, pola opcjonalne w `raw_payload`), powiadomienie linkuje
  do profilu. „Zgłoszenia” zdjęte z menu i ⌘K; strona i resolver zostają dla
  starych wierszy i linków z powiadomień.
  Pułapka na boty `website` = cichy 201 bez zapisu. `new_application` do
  właściciela linku po commicie.
- **Routing po hoście** (`middleware.ts`, env `NEXT_PUBLIC_CAREER_HOST`): na
  domenie kariery nie działa żadna logika logowania, dozwolone są tylko `/`,
  `/r/*`, `/rodo`, `/<slug>`, `/kariera/*` i `/_next`; reszta = 404. Pusta
  zmienna = routing wyłączony, strona żyje pod `/kariera/*` na hoście aplikacji
  (publiczna ścieżka) i tam prowadzą linki (`career_base_url()` bez
  `CAREER_PUBLIC_BASE_URL` = `PUBLIC_BASE_URL/kariera`). `AppShellV2` renderuje
  gołą stronę po segmencie `kariera` — po rewrite `usePathname()` zwraca adres
  widoczny, nie wewnętrzny.
- **Fonty strony kariery (Geist, JetBrains Mono) są lokalne** i ładowane tylko w
  jej layoucie; grafiki OG czytają TTF przez `fs`, stąd
  `outputFileTracingIncludes` w `next.config.ts` (obraz standalone).
- Klauzula `/kariera/rodo`: kontakt rodo@b2bnetwork.pl, okres przechowywania
  3 lata od zgłoszenia lub do cofnięcia zgody (decyzja Artura 27.09.2026, F16).
- **Marka i domena (decyzje C i marka, 19.10.2026):** strona mówi „B2B Network”
  (`~/b2bnetwork/kariera`, `marta@b2bnetwork`, karta „… — B2B Network”), bez
  haseł Dynaminds („Architects of the unseen”, manifest „Define tomorrow”).
  Docelowa domena `kariera.b2bnetwork.pl`; slug `b2bnetwork` zarezerwowany.
  Gdy `NEXT_PUBLIC_CAREER_HOST` jest ustawiony, middleware przekierowuje stare
  adresy z hosta aplikacji (`/kariera`, `/kariera/rodo`, `/kariera/r/<slug>`,
  `/kariera/p/<slug>`) na domenę kariery — 307, z query (UTM); grafiki OG
  i `/kariera/nie-znaleziono` zostają (`legacyCareerRedirectPath`).
- Aktywacja domeny (kolejność ma znaczenie — przekierowanie działa od buildu
  z `NEXT_PUBLIC_CAREER_HOST`, więc domena musi odpowiadać wcześniej):
  1. rekord DNS `kariera.b2bnetwork.pl` → serwer NEXUSA (gdzie stoi strefa
     `b2bnetwork.pl`, tam rekord);
  2. domena `https://kariera.b2bnetwork.pl` w Coolify dla serwisu frontend
     (obok obecnej), certyfikat LE — sprawdź `curl -I`;
  3. workflow „Coolify set env”: `CORS_ORIGINS` + `https://kariera.b2bnetwork.pl`,
     `CAREER_PUBLIC_BASE_URL=https://kariera.b2bnetwork.pl`,
     `NEXT_PUBLIC_CAREER_HOST=kariera.b2bnetwork.pl` (`is_buildtime=true`);
  4. deploy w oknie 19:00–07:00, potem `/r/<slug>` na nowej domenie, stary
     `nexus…/kariera/r/<slug>` → 307, formularz wysyła (CORS).
