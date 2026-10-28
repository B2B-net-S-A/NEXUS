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
- **Strona rekrutera (etap 6, 20.10.2026, makieta 6d w
  https://claude.ai/artifact/8aVZkzVxkVnkVVNBUDgL4h):** inicjał zamiast zdjęcia,
  samo imię, „O mnie”, plakietki kategorii z otwartych rekrutacji, lista
  rekrutacji (bez nazwy sceny od 28.10.2026), formularz „Zostaw CV u <imię>” (ta sama ścieżka
  `submit_application`, jedna zgoda — niżej) i odesłanie do tablicy `/`.
  `GET /api/public/career/p/{slug}` zwraca `recruiter.about`, a każda
  rekrutacja `theme` (szablon, jak na `/r/`) i `category` — ten sam klucz co
  tablica (`career_board.public_category`: development / infra / qa /
  management; nazwy w `lib/career/board.ts`, `categoryChips`). Kształt
  pilnuje `_RECRUITER_JOB_KEYS` w `test_career_links_api.py`.
- **„O mnie” = `candidate_invite_links.about` (0489)**, najwyżej 280 znaków,
  zapis `PUT /api/me/career-link` z `about` (pominięte = bez zmian, pusty
  tekst = usuń), okno „Udostępnij” → „Mój link ogólny”. Na linku, nie na
  `users`: tekst należy do publicznej strony, zmiana adresu i odzyskanie
  odwołanego linku zostawiają ten sam wiersz. Zapis wycina znaki formatujące
  (`visible`) i zlewa nowe linie, potem `lint_public_texts` (klienci otwartych
  rekrutacji osoby — prowadzonych albo z jej linkiem; jej własne imię
  i nazwisko) + `lint_internal_codes`. Znalezisko = 422
  `CAREER_ABOUT_FINDINGS` z listą i nic się nie zapisuje (także adres) —
  „O mnie” nie ma kroku zatwierdzenia, idzie na stronę od razu.
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
- **Tytuły Nordei** (29.10.2026, decyzja Artura): tytuł domyślny zdejmuje też
  numer zapotrzebowania `TP#41745` / `TP ID 40942`, kraj i zespół na początku
  (`PL - MDM - `, `PL_KYC_`, `PL-EBSD-`; `PL/SQL`, `PL-300` i `IT_` po kraju
  zostają) oraz `Replacement (for …)` na końcu albo na początku (bywa w nim
  imię i nazwisko osoby; „Replacement (open request)” zostaje, bo bez niego nie
  ma roli). Kontrola `internal_code` zna `TP#` i `TP ID`.
- **Zdjęcie samych kodów nie wymaga ponownego zatwierdzenia** (29.10.2026,
  decyzja Artura): gdy dzisiejszy tytuł domyślny to zatwierdzony tytuł bez
  kodów, a treść się nie zmieniła, opis zostaje „Zatwierdzony” i strona, OG
  i maile od razu pokazują nowy tytuł (`_approved_title_with_codes`). Wersja
  opublikowana sprzed zmian w edytorze też dostaje tytuł bez kodów. Do migawki
  idzie tytuł, z którym policzono skrót (`PublishedVersion.approved_title`) —
  inaczej pierwsza zmiana opisu zdjęłaby stronę. Adres linku się nie zmienia.
- **Kontrola kodów wewnętrznych** (`lint_internal_codes`, kod `internal_code`):
  `RITM|REQ|SCTASK|ZOB|PKN|EITE` z co najmniej 4 cyframi, `TP#` (Nordea) i części
  `client_reference` (od 4 znaków). Czyta ją tylko `lint_payload` (opis
  i tytuł), NIE kontrola adresu — znalezisko w adresie wymieniłoby rozesłany
  link (stary daje 404), a numer w adresie to kosmetyka.
- **Strony kariery są w Google** (etap 6, decyzja D3 Artura 20.10.2026, makiety
  plansze 6a–6e na https://claude.ai/artifact/8aVZkzVxkVnkVVNBUDgL4h):
  - layout kariery ma `index, follow`; zamknięta rekrutacja sama ustawia
    `noindex` (`r/[slug]`), `/rodo` zostaje `noindex`, a nieznany slug dostaje
    stronę 404 z `noindex` od Next.js;
  - **kod HTTP nieznanego adresu to nadal 200**: `app/loading.tsx` wysyła
    odpowiedź, zanim strona zdąży wywołać `notFound()` — także z metadanych.
    Prawdziwe 404 wymaga przebudowy granic ładowania całej aplikacji; Google
    i tak nie indeksuje takiej strony (`noindex`);
  - `app/robots.ts` jest zależny od hosta: domena kariery `Allow: /` (także
    `/kariera/*` z grafikami OG — LinkedIn czyta robots), host aplikacji
    `Disallow: /`. Middleware pomija ścieżki z kropką, więc przepisanie
    `/robots.txt` w `resolveCareerRoute` by nie zadziałało;
  - strona otwartej rekrutacji niesie dane JobPosting (`lib/career/jobPosting.ts`):
    tytuł, opis z opublikowanej wersji, `datePosted` = `published_at` z API
    (data zatwierdzenia, bez godziny), `CONTRACTOR`, B2B Network, miejsce albo
    praca zdalna z Polski. Bez klienta i bez stawek; adres kanoniczny na
    domenie kariery;
  - `app/sitemap.ts` zależny od hosta: na domenie kariery strona główna
    i `/r/<slug>` z listy tablicy (`GET /api/public/career/jobs`, zamknięta
    rekrutacja znika z listy), w aplikacji pusta mapa; awaria API = sama
    strona główna. `robots.txt` domeny kariery wskazuje mapę (`Sitemap:`);
  - ikona segmentu kariery (`app/kariera/icon.svg`) zamiast fioletowego logo
    NEXUSA; grafika OG strony głównej (`app/kariera/opengraph-image.tsx`).
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
- **Stały link rekrutera `/p/<slug>` ma JEDNĄ zgodę (decyzja Artura
  19.10.2026, wieczór):** „Dołącz do bazy” nie dotyczy żadnej rekrutacji, więc
  obowiązkowe pole `consent` niesie tam treść `CONSENT_FUTURE_TEXT` i zapisuje
  wiersz `recruitment_future`; zgody „na tę rekrutację” ani pola
  `consent_future` tam nie ma. Reguła w jednym miejscu:
  `career_consent.consent_kinds(link.kind, …)` (backend) i `variant="general"`
  w `CareerApplyForm` (front). Treść zgód bez zmian; klauzula `/rodo` ma o tym
  jedno zdanie w pkt 3.
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
- **Trzy szablony ogłoszeń w barwach B2B Network (decyzja Artura 28.10.2026,
  makiety https://claude.ai/artifact/RGquQpMFyKgRYHPognJ2kU, warianty A, C i B).**
  Zespół (Teams, 28.10) ocenił ogłoszenia jako nieczytelne, „nie w szacie B2B”
  i „jakby się nie doładowały”. Pomiar na AMLR/KYC: 51% tekstu ≤ 13 px,
  wymagania trzy razy na stronie, na telefonie pierwszy ekran bez miasta,
  umowy i „Aplikuj”. 12 szablonów ze scenami ról (0478, 19–20.10.2026)
  zastąpiły trzy układy z `components/career/layouts/`:
  - `grafit` (C, domyślny): ciemny grafit, czerwień i łuk znaku B2B, fakty
    w kaflach, treść w układzie „bento”;
  - `terminal` (A): klimat terminala bez granatu i scen, karta „Co już masz?”;
  - `jasny` (B): tło Snow z brand booka, białe karty.

  Domyślny wynika z roli w tytule (`services/career_theme.role_theme`).
  Dev, testy i DevOps dostają `terminal`; PM, delivery, scrum, PO i analityk
  dostają `jasny`. Architekt, data, security, sieci i admin dostają `grafit`.
  Potem kategoria (`software_development`, `security_quality` → `terminal`,
  `management_delivery` → `jasny`), na końcu `grafit`. Wybór rekrutera
  w `job_public_profiles.theme`, zapis samym `PUT …/public-profile {theme}`,
  **poza skrótem treści**, więc zmiana wyglądu nie cofa zatwierdzenia.
  - Zapisany wybór jednej z 12 dawnych scen zostaje w bazie, ale
    `resolve_theme` traktuje go jak brak wyboru. Opublikowane linki dostały
    nowy wygląd od razu, bez ponownego zatwierdzania. `PUT` z dawną sceną
    daje 422, a „Udostępnij” pokazuje wtedy domyślny jako wybrany.
  - Wspólne zasady układów (przy zmianie pilnuj ich we wszystkich trzech):
    pierwszy ekran 1280 × 720 i 390 × 844 pokazuje tytuł (jedyny `<h1>`),
    Lokalizację, Tryb pracy, Umowę i „Aplikuj”. Tekst do czytania ma
    ≥ 16 px (desktop 17–19), etykiety ≥ 14 px, a 13 px tylko stopka
    prawna. Wymagania stoją na stronie raz, a „Mile widziane” osobno.
    „Czym się zajmiesz: a; b; c” idzie jako punkty (`layouts/jobModel.ts`).
    Nie ma pustych ramek, pasków ani „0%”. Sekcje mają `aria-label`:
    „O projekcie”, „Wymagania”, „Proces rekrutacji” (4 kroki w `<ol>`)
    i „Aplikuj” (`id="aplikuj"`).
  - Formularz jest jeden: `CareerApplyForm` z `tone="plain"` (zdania zamiast
    `// …`, `[err]`, `ENTER`) albo `tone="terminal"`. Każdy układ stylizuje
    jego klasy `.kr-*` z poziomu swojego modułu CSS. Logika wysyłki, zgody
    i pułapka na boty są wspólne.
  - Kolory z `components/career/themes.ts` (jedno źródło dla strony, grafiki
    OG i podglądu posta; lista id = `THEME_LABELS` w backendzie, test).
    Czerwień marki `#E73748` jest w tytułach i ozdobnikach. Przycisk ma
    `#D62E40`, bo biały tekst na `#E73748` daje 4,2:1, a test wymaga 4,5:1.
    Plakat: `career_theme.POSTER_COLORS`.
  - Kroje: Montserrat (globalna, `globals.css`) i Source Sans 3 (lokalnie,
    `layouts/brandFonts.css`, nigdy Google Fonts w buildzie).
  - Harness: `/preview/kariera?szablon=<id>`.

- **Strona główna = tablica otwartych rekrutacji (etap 6, decyzje Artura
  D1 = A i D2 = A, 20.10.2026, makiety 8aVZkzVxkVnkVVNBUDgL4h, plansze 6b,
  6c, 6e).** `GET /api/public/career/jobs` (publiczna, 60/min, cache 60 s
  z single-flight, `services/career_board.py`) zwraca karty z białej listy:
  tytuł i podtytuł z wersji opublikowanej, miasto i tryb jak `/r` (migawka
  + przełącznik „parametry”), klucz kategorii (`development`, `infra` —
  także `data_ai`, `qa`, `management`), scena (`resolve_theme`) i imię
  właściciela linku karty. Nigdy klient, stawki, budżet ani kody — test
  kształtu karty w `test_career_links_api.py`.
  - **Co jest na tablicy:** KAŻDA rekrutacja `published` z
    `jpp.published_version` (nie `status == approved`, nie przełącznik
    „pokazuj na mojej stronie” — ten dotyczy tylko `/p/<slug>`). Zamknięcie
    rekrutacji zdejmuje kartę (najpóźniej po 60 s cache).
  - **Czyj link wskazuje karta (D2):** prowadzący (`working_owner_id`:
    `jobs.recruiter_id`, aktywne konto, nie „poprzedni rekruter”) z aktywnym
    linkiem `job` → ten link; prowadzący bez aktywnego linku, który żadnego
    nie wyłączył (nigdy nie miał albo mu wygasł) → tablica zakłada mu nowy
    przy budowaniu (etykieta
    „Tablica kariery”, przypisanie priorytetowe jak `POST /api/invite-links`,
    blokada doradcza `career_board_links` przeciw dublom). Nie przy
    zatwierdzeniu opisu, bo prowadzący zmienia się później — tablica sama
    dobiera link nowej osoby. Prowadzący, który swój link WYŁĄCZYŁ, nowego nie
    dostaje — karta bierze najnowszy aktywny link innej osoby. Bez prowadzącego:
    najnowszy aktywny link rekrutacji, a bez niego nowy link pierwszego
    aktywnego Head of Recruitment (najniższe id, jak „Zostaw CV”), chyba że ten
    swój link do rekrutacji wyłączył. Decyzja Artura 21.10.2026: 20.10 tablica
    na produkcji była pusta, bo jedyna rekrutacja z linkiem miała go wygasłego
    od 05.10, a druga nie miała prowadzącego ani linku (`_pick_link`,
    `_first_hor_id`). Zgłoszenie z karty idzie zwykłym `/apply` linku,
    więc blokada 12 h, „Z linków” i dzwonek należą do właściciela linku.
  - **Linki osób z wyłączonym kontem się nie liczą** (decyzja Artura
    22.10.2026, audyt F62): tablica i `canonical_job_slug` odrzucają linki,
    których właściciel ma `is_active = false`, zanim wybiorą link karty
    (`_links_of_active_owners`). Wyłączenie konta unieważnia tylko link
    `recruiter`, więc link `job` osoby, która odeszła, wisiał „aktywny” bez
    końca: karta pokazywała jej imię publicznie i w Google, a zapas na Head
    of Recruitment się nie uruchamiał. Rekrutacja z samymi takimi linkami
    dostaje link HoR jak rekrutacja bez prowadzącego. Sam stary link dalej
    działa (zgłoszenie idzie do zespołu rekrutacji), tylko nie stoi na tablicy.
  - **„Zostaw CV” (bez rekrutacji):** stały link Head of Recruitment
    (`board_cv_link`, w odpowiedzi `cv: {slug, first_name}`), formularz
    `variant="general"` z jedną zgodą na przyszłe procesy — osoba ląduje
    w bazie, w „Moich ludziach” HoR, dzwonek `new_application` do HoR.
    Kilku HoR: pierwszy (najniższe id) z aktywnym stałym linkiem; gdy żaden
    go nie ma — pierwszy, który nigdy go nie miał, dostaje link teraz (adres
    z imienia jak podpowiedź w „Mój link”). HoR, który wyłączył stały link,
    nie dostaje nowego. Zero HoR albo wszyscy wyłączyli → `cv: null`,
    tablica bez „Zostaw CV” (ostrzeżenie w logu).
  - **Front** (`components/career/CareerBoardView.tsx`, logika filtrów
    `lib/career/board.ts`): kategorie z licznikami (liczone po szukaniu
    i trybie, bez samej kategorii; puste kategorie schowane), szukanie bez
    polskich znaków (każde słowo w tytule, podtytule, mieście albo
    wymaganiach), tryb pracy (kilka = „lub”), 12 wierszy i „pokaż kolejne”,
    znak i podgląd sceny w barwach szablonu (`BoardPreview.tsx`, etap 7),
    na telefonie kategorie łamane w wiersze i przyklejone „Zostaw CV”,
    znikające, gdy sekcja jest na ekranie. „Brak otwartych rekrutacji” tylko przy udanym odczycie;
    awaria API = komunikat „Chwilowa przerwa”, nigdy pusta lista. Kontrast
    tekstu kart i etykiet scen ≥ 4,5:1 pilnuje `CareerBoardView.test.tsx`.
    Harness: `/preview/kariera#tablica` (plus `#tablica-pusta`,
    `#tablica-awaria`).
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
- **Krój i poprawki po audycie etapu 7 (decyzje D1–D4, 21.10.2026):** tekst do
  czytania (opisy, kroki procesu, formularz, chipy tablicy, RODO, stopka) jest
  w Geist 400/500 (`--kr-sans`), a JetBrains Mono zostaje przy komendach `$ …`,
  komentarzach `// …` i parametrach (`--kr-mono`, domyślny krój
  `.kr-root`). Nowy element do czytania dopisz do listy `--kr-sans` na końcu
  `career.css`, zamiast zmieniać krój korzenia. Etykiety formularza są zdaniem
  („Imię *”, „CV *”), bez wersalików. Tytuł od 1024 px nie dzieli wyrazów
  (`hyphens: manual`; wcześniej „kolej-nego” na stronie rekrutera), na
  telefonie dzieli dalej. Pod stroną nie ma siatki. Strona rekrutacji od
  28.10.2026 ma własne kroje w układach (wyżej). Chipy kategorii na telefonie łamią się do nowego
  wiersza. Dalsze etapy (tablica z podglądem i Flip, „Sprawdź się” na
  ScrollTrigger, Lenis) są na planszach 7a–7c kanwy
  https://claude.ai/artifact/8aVZkzVxkVnkVVNBUDgL4h i w prototypie
  https://claude.ai/artifact/TsUgULCMSSjVTiYWvoGN3b.
- **Tablica jako lista z żywym podglądem (etap 7, D2 = A, 21.10.2026):**
  karty zastąpiła lista wierszy (znak szablonu, tytuł, podtytuł, „miejsce ·
  kategoria · rekruter”, „Zobacz”). Od 1024 px obok listy stoi przyklejony
  podgląd (`BoardPreview.tsx`): najechanie albo fokus na wierszu buduje szkic
  rekrutacji z jej wymagań w kolorach szablonu (od 28.10.2026 trzy układy
  szkicu, po jednym na szablon).
  Podgląd jest dodatkiem dla myszy (`aria-hidden`, `tabIndex=-1`); klawiatura
  i czytnik idą wierszami. Karta tablicy niesie `must`/`nice` (najwyżej po 5,
  z tej samej projekcji co strona rekrutacji — ukryta sekcja daje pustą listę;
  klucz cache `career_board:v2`), a szukanie obejmuje też wymagania. Filtr
  przestawia wiersze przez GSAP Flip, licznik „x z N” stoi w polu szukania.
  Ruch tylko od 1024 px i bez „ograniczonego ruchu” (`gsap.matchMedia`); bez
  `matchMedia` (jsdom) scena stoi. GSAP 3.13.0 i `@gsap/react` 2.1.2 ładuje
  wyłącznie strona kariery.
- **„Sprawdź się”, oś procesu i dolny „Aplikuj” z etapu 7 (PR C, 21.10.2026)**
  odeszły razem ze scenami 28.10.2026 (`FitSection`, `ProcessSteps`,
  `ApplyDock`). Odpowiedniki są w układach: karta „Co już masz?” w Terminalu,
  sekcja „Proces rekrutacji” i przyklejony pasek „Aplikuj” na telefonie.
- **Moment otwarcia i płynny scroll (etap 7, PR D, D3 = A, 21.10.2026):**
  `CareerMotion.tsx` (montują go widoki tablicy, rekrutacji i rekrutera, nie
  układ `/kariera` — strona za `loading.tsx` dochodzi strumieniem i efekt
  w układzie ruszał przed hydratacją tytułu; po jednym na korzeń `.kr-root`) przy każdym adresie wysuwa linie tytułu `.kr-title` spod maski
  (SplitText) i raz rozszyfrowuje komendę z `data-kr-scramble` (ScrambleText).
  Po animacji SplitText przywraca oryginalny tytuł, a sprzątanie efektu
  (StrictMode, zmiana adresu) zabija animacje, cofa podział i odtwarza tekst
  komendy — inaczej tytuł zostawał podzielony dwa razy i schowany pod maską.
  Dzielenie czeka na `document.fonts.ready`. Lenis działa tylko od 1024 px
  z myszą i bez „ograniczonego ruchu”, jeden na dokument (harness ma wiele
  korzeni), napędza ScrollTrigger i przewija kotwice `#…`, a po przewinięciu
  przenosi fokus na cel (`#aplikuj` ma `tabIndex={-1}`). Zrzut przed hydratacją w Playwright wstrzykuje
  `caret-color` i daje fałszywy błąd hydratacji — sprawdzaj po `networkidle`.
- **Jedna oferta w Google na rekrutację (audyt etapu 7, 21.10.2026):** każdy
  link `/r/<slug>` tej samej rekrutacji ma ten sam `canonical` i `identifier`
  JobPosting — link z tablicy (`career_board.canonical_job_slug`, pole
  `canonical_slug` w odpowiedzi `/r/{slug}`). Inaczej linki rekruterów dawały
  w Google kilka kopii tej samej oferty. JobPosting bez miasta i bez pracy
  zdalnej nie powstaje (Google odrzuca ofertę bez lokalizacji), a
  `TELECOMMUTE` stoi tylko przy `remote`.
