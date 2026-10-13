# Strona kariery dla kandydatów (kariera.dynaminds.pl, 0339, 22.09.2026)

Publiczny landing, który rekruterzy wrzucają na LinkedIna. Raport:
`docs/career-landing-completion-report.md`. Dwa rodzaje linku w
`candidate_invite_links` (`kind`):
- **`job`** — `/r/<slug>`: opis publiczny rekrutacji + formularz; kandydat
  trafia na etap „Nowy” tej rekrutacji po przeglądzie AI (0404 — sekcja
  „Zgłoszenia z linku rekrutacji przegląda AI” wyżej). Domyślnie **bez terminu** — ważny, póki
  rekrutacja jest otwarta (zamknięta = strona „proces zakończony” z odesłaniem
  do stałego linku rekrutera; stare `/apply/{token}` też dają wtedy 404).
- **`recruiter`** — `/<slug>` (np. `/marta-n`): stały link do bazy, jeden
  aktywny na osobę (częściowy UNIQUE). Bez rekrutacji: brak `open_process`,
  `CandidateSourceEvent.job_id = NULL`, osoba **przypięta w „Moich ludziach”**
  właściciela linku (`my_people` nie czyta `created_by`).

Reguły, które łatwo cofnąć:
- **Na stronę trafia wyłącznie zatwierdzony opis publiczny**
  (`job_public_profiles`, status liczony z hasha treści — edycja po zatwierdzeniu
  = szkic). Niezatwierdzony profil = 404. Publiczne GET-y budują odpowiedź z
  białej listy (`services/job_public_profile.py`): **nigdy klient, stawka,
  budżet ani nazwisko rekrutera** (tylko imię). Pilnuje test kształtu odpowiedzi.
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
- Aktywacja domeny: rekord DNS `kariera` w Cloudflare → serwer NEXUSA, domena
  w Coolify dla serwisu frontend, env `NEXT_PUBLIC_CAREER_HOST` (build arg),
  `CAREER_PUBLIC_BASE_URL` i `CORS_ORIGINS` + `https://kariera.dynaminds.pl`.
