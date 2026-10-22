# Ogłoszenie na portale — treść do wklejenia w Pracuj.pl i JustJoin.IT (0430 i 0432, 12–13.10.2026)

<!-- indeks: kontrola przed skopiowaniem, „Oznacz jako opublikowane” -->

Od 21.10.2026 okno nazywa się „Ogłoszenie” i ta sama treść zasila stronę
kariery — `ogloszenie-jedna-tresc-strona-kariery.md`.

Decyzje Artura 12.10.2026 (makiety https://claude.ai/artifact/NK7tLYnrh1mNgH7MQ8MhtX).
Pomiar naszych publicznych ogłoszeń tego dnia (50 na JustJoin.IT, 15 na
Pracuj.pl): „co oferujemy” miały 4 z 50 i 5 z 15, etapów procesu żadne z 50,
pięć było wklejonym wewnętrznym formularzem requestu („Stawka kandydata: …”),
jedno miało inne widełki w nagłówku i w treści, a tytuły sześć różnych
dopisków. Rekruterzy układali treść w ChatGPT. Stary „Szkic ogłoszenia”
(`ai_writer`) był szablonem bez modelu, który dopisywał „Klient: …”.

Kod: `services/job_ad/` (`material`, `generate`, `render`, `lint`,
`fixed_blocks`), `api/job_ads.py`, tabela `job_ads` (jedno ogłoszenie na
rekrutację); front `components/v2/job-ad/`, `lib/api/jobAd.ts`, karta
`components/settings/JobAdFixedBlocksCard.tsx`. Harness `/preview/job-ad`
(`?state=ready|findings|template|empty`, `?tab=jjit`).

- **Jedna treść, dwa formaty.** `job_ads.content` + `tech` zapisuje się raz,
  a `render.render_ad` składa z nich pola formularza Pracuj.pl i opis
  JustJoin.IT. Nie dokładaj osobnej treści per portal — rozjazd między
  portalami to dokładnie błąd z pomiaru.
- **Do schowka idą WYŁĄCZNIE teksty `rendered` z odpowiedzi serwera** —
  policzone dla zapisanego stanu, po kontroli. Front nie formatuje treści
  sam, podgląd rysuje jako zwykły tekst (HTML z odpowiedzi nigdy nie trafia
  do `dangerouslySetInnerHTML`), a kopiowanie jest wyłączone, gdy pole jest
  w edycji, trwa zapis albo `can_copy` jest fałszem.
- **Materiał = to, co wolno powiedzieć** (`material.build_material`): opis
  projektu, obowiązki, wymagania, notatki „Można powiedzieć kandydatowi” —
  przez `job_public_profile.draft_material`, tę samą funkcję co szkic strony
  kariery. Nigdy pola klienta, stawka, sekcja `client` ani notatki „Tylko
  zespół”. Nazwę klienta wpisaną przez kogoś w opisie projektu albo
  w wymaganiach model zobaczy — dlatego wynik zawsze przechodzi kontrolę.
  Z `basics` Championa czytane jest tylko `language` (sekcja niesie stawkę).
  Opis rekrutacji traci linie `Klient: …` i znaczniki `##` zostawione przez
  stary szkic.
- **Model redaguje, kod dokleja.** Model (klucz `job_description_generator`,
  rejestr `ai_models`) oddaje wstęp, opis projektu, obowiązki, wymagania, mile
  widziane i punkty z „co wolno powiedzieć”. Tytuł, tryb pracy, miasto, start,
  długość, „co oferujemy” firmy i etapy procesu składa `render` z pól
  rekrutacji i stałych bloków — tam model nie ma czego zmyślać. W wersji
  angielskiej model dodatkowo TŁUMACZY start, długość i język pracy; wartości,
  której rekrutacja nie ma, nie wolno mu dopisać (`generate.with_terms`).
- **Awaria modelu nie zastępuje zapisanej treści.** Złożenie z pól rekrutacji
  (`source="template"`, baner w oknie) powstaje tylko jako PIERWSZA wersja
  ogłoszenia i tylko po polsku. „Przygotuj ponownie” przy niedostępnym modelu
  = 503 bez zapisu — rekruter mógł już poprawić treść. Poprzedni generator
  oddawał w takiej sytuacji szablon ze zmyślonymi widełkami, nie do
  odróżnienia od wyniku AI.
- **Zapis po odpowiedzi modelu jest warunkowy.** Model liczy do minuty, więc
  `generate` zapisuje tylko wtedy, gdy ogłoszenie jest wciąż w wersji sprzed
  wywołania (`UPDATE … WHERE updated_at = <widziana>` albo `INSERT … ON
  CONFLICT DO NOTHING` dla pierwszej wersji). Zero zapisanych wierszy = 409
  `job_ad_changed`. Bezwarunkowy upsert zastępował poprawkę zapisaną
  w trakcie i pozwalał złożeniu bez modelu nadpisać cudze ogłoszenie.
- **Kontrola (`lint.lint_ad`) czyta wszystko, co idzie do schowka:** pola
  ogłoszenia, miasto z rekrutacji (`terms`), stałe bloki (`fixed`) i na końcu
  komplet napisów z `render.rendered_texts`. Nowe wejście renderu = nowy
  przypadek w teście z wartownikiem (`test_job_ad_lint.py`).
  **Blokują:** nazwa klienta (także nazwa wyświetlana i prawna —
  `job_public_profile.client_lint_names`), dane kontaktowe, nazwisko,
  kwota z walutą albo stawką za jednostkę czasu oraz liczba przy słowie
  „budżet”, „widełki”, „wynagrodzenie”, „salary”, „pensja”, „zarobki”
  (od 14.10.2026, niżej). **Doradzają:** liczba przy
  słowie „stawka”/„rate” bez waluty („rate limiting … Java 17”), adres strony
  bez „www”, nagłówki wewnętrznego formularza, liczby MD, numer zlecenia,
  wymaganie w jednym–dwóch słowach, brak startu, długości albo sekcji.
- **O tym, czy kwota blokuje, decydują wzorce strony kariery**
  (`public_profile_lint.CERTAIN_MONEY_PATTERNS`), nie ich kopia. Własny,
  węższy wzorzec przepuszczał „15 tysięcy zł” i „180/godzinę” jako uwagę
  (przegląd 12.10.2026). Od 13.10.2026 reguły blokujące mają JEDNO źródło
  ze stroną kariery: kwota słownie („200 złotych”, „30 tys. netto”,
  „2 mln PLN”), link (`http`, `www`), telefon stacjonarny i z numerem
  kierunkowym, e-mail zapisany jako „jan [at] firma” siedzą
  w `public_profile_lint.py` i tam dopisuje się kolejne. W `job_ad/lint.py`
  zostaje tylko to, czego strona kariery nie ma: poziom „uwaga” (liczba przy
  słowie „stawka”, adres bez „www”, nagłówki formularza, MD, numer zlecenia,
  braki). Końcówek „.net”, „.io”, „.js” kontrola nie traktuje jak adresu —
  to nazwy technologii.
- **Znaki niewidoczne nie chowają znaleziska.** Tekst z Worda i PDF-a niesie
  miękkie łączniki i spacje zerowej szerokości; kontrola porównuje tekst po
  `public_profile_lint.for_lint` (NFKC, bez znaków formatujących), a zapis
  i render je wycinają (`job_ad/text.visible`; łącznik sklejający emoji
  zostaje).
- **Nazwa klienta jest dopasowywana po całych słowach**, jak na stronie
  kariery: odmienioną formę („w Kwarcowym Banku”) łapie dopiero alias klienta.
- **Widełki wpisuje człowiek w formularzu portalu** (decyzja z 25.09.2026
  bez zmian): okno ich nie podpowiada, a w treści ogłoszenia kwot nie ma.
- **Stałe części firmy** (`app_settings['job_ad_fixed_blocks']`, Ustawienia →
  Rekrutacja → „Stałe części ogłoszenia”, admin i Head of Recruitment):
  dopisek do tytułu, „co oferujemy”, etapy procesu i zdanie o firmie, osobno
  po polsku i po angielsku. Zapis odmawia kwot i danych kontaktowych — blok
  trafia do każdego ogłoszenia, a rekruter go nie poprawi. Wartości startowe
  to punkty z publicznych profili firmy na portalach.
- **Lista technologii bierze tylko krótkie pozycje** (do 3 słów i 40 znaków,
  zamienniki „X lub Y” osobno). Zdanie klienta zostaje w wymaganiach. Poziom
  JustJoin.IT: krytyczne (wyłącznie z decyzji Delivery Leada) → Advanced,
  wymagane → Regular, mile widziane → Nice to have; okno mówi, ile
  technologii nie zmieściło się w limicie 10.
- **`material_hash` liczy się z jawnej, wersjonowanej listy pól**
  (`material._HASH_FIELDS`). Nowe pole `AdMaterial` dopisane do odcisku bez
  zmiany wersji oznaczy wszystkie zapisane ogłoszenia jako „rekrutacja się
  zmieniła”.
- **Zapis poprawki i ponowne przygotowanie niosą `expected_updated_at`**;
  inna wersja w bazie = 409 `job_ad_changed`, okno wczytuje ogłoszenie
  ponownie, a niezapisany tekst zostaje w polu. Wysyłana jest wersja, od
  której ZACZĘŁA SIĘ edycja (`baseVersion` w `JobAdWindow`), nie ta z cache
  w chwili zapisu: zapytanie odświeża się w tle przy powrocie do karty
  i stary tekst przeszedłby jako poprawka do cudzej, nowszej treści. Własny
  udany zapis przesuwa wersję bazową, więc dwa pola otwarte naraz zapisują
  się po kolei bez fałszywego konfliktu.
- **Niezapisany tekst trzyma okno, nie blok** (`drafts` w `JobAdWindow`, dla
  pól obu zakładek i warunków z lewej kolumny). Nieaktywna zakładka jest
  odmontowana, a „Pokaż” z kontroli samo przełącza zakładkę — stan lokalny
  bloku gubił poprawkę. Opis JustJoin.IT kopiowany w całości jest wyłączony,
  dopóki któraś jego sekcja ma otwartą poprawkę.
- **To nie jest publikacja przez API.** Sekcja „Portale ogłoszeniowe”
  (`JobPortalsSection`, tabela `job_postings`, treść z zatwierdzonego opisu
  publicznego) zostaje osobno i za flagami. Ręcznie wklejonego ogłoszenia nie
  zapisuj w `job_postings`: to kolejka workera, więc taki wiersz dostałby
  zlecenie wysyłki przez API, a przy Pracuj.pl trwale blokował usunięcie
  rekrutacji. Połączenie obu treści to osobny etap.
- **Oznaczenie publikacji to zapis tego, co zrobił człowiek (0432).** Tabela
  `job_ad_publications` (jeden wiersz na rekrutację i portal: `pracuj`,
  `jjit`), logika `services/job_ad/publications.py`, trasy
  `PUT/DELETE /api/jobs/{id}/portal-ad/publications/{portal}`, front
  `components/v2/job-ad/AdPublications.tsx` (okno i sekcja „Zespół
  i ogłoszenie”) oraz kolumna „Ogłoszenia” listy (`JobAdPublicationsCell`).
  NEXUS niczego na portalu nie publikuje ani nie zdejmuje — także przy
  zamknięciu rekrutacji; wtedy sekcja i lista tylko przypominają o zdjęciu.
  - **Link przyjmujemy wyłącznie z domeny portalu** (`pracuj.pl`;
    przy JustJoin.IT `justjoin.it` albo `rocketjobs.pl`, bo RocketJobs
    połączył się z JustJoin.IT i ogłoszenie wisi też tam — 14.10.2026): http/https i sam host — bez portu, danych logowania,
    znaków spoza ASCII i bez ukośnika wstecznego gdziekolwiek w adresie
    (`publications.clean_url`). Odnośnik z listy rekrutacji prowadzi prosto
    na zewnątrz, więc dowolny adres byłby dziurą. Przeglądarka czyta „\”
    w http(s) jak „/”, a `urlsplit` nie: „https://obca.strona\.pracuj.pl/”
    przechodziło walidację i otwierało obcą stronę (przegląd 13.10.2026).
    Dlatego przy samym `href` adres sprawdza jeszcze parser przeglądarki
    (`portalAdHref` w `lib/api/jobAd.ts`) — nowe miejsce pokazujące link
    bierze go stamtąd, nie z pola `url`. Link jest opcjonalny: ogłoszenie na
    Pracuj.pl bywa widoczne dopiero po moderacji.
  - **„Do aktualizacji” = odcisk zapisanej treści** (`content_hash`: język,
    pola, technologie) inny niż w chwili oznaczenia. Liczy się z samego
    wiersza `job_ads`, żeby lista policzyła go jednym zapytaniem na stronę
    (`publications.for_jobs`, wzór `recruiters_for_jobs`). Zmiana samej
    rekrutacji albo stałych bloków firmy plakietki nie zapala — o zmianie
    rekrutacji mówi baner „Rekrutacja zmieniła się…” w oknie.
  - **Trzy zdarzenia, nie jedno nadpisanie wiersza** (`mark_published`):
    pierwsze oznaczenie albo powrót po zdjęciu zapisuje link, odcisk treści
    oraz kto i kiedy; zmiana samego linku przy aktywnym oznaczeniu zmienia
    TYLKO link (rekruter dopisuje go po moderacji portalu — to nie
    potwierdza treści i nie zmienia, kto opublikował); „Zaktualizowane na
    portalu” (`content_updated`) odświeża odcisk, daty publikacji nie rusza.
    Jedno wspólne nadpisanie gasiło „do aktualizacji” przy dopisaniu linku
    (przegląd 13.10.2026).
  - **Potwierdzić wolno tylko treść bez znalezisk blokujących** (409
    `job_ad_blocked`): takiej treści nie wolno było wkleić. Dotyczy
    pierwszego oznaczenia i „Zaktualizowane na portalu”; sam link da się
    zmienić zawsze.
  - **„Zdjęte z portalu” zostawia wiersz** (`removed_at`); lista i szczegół
    rekrutacji niosą w `ad_publications` tylko aktywne ogłoszenia.
  - Sekcja czyta stan z tego samego zapytania co okno (`jobAdQueryKey`),
    a po zmianie odświeża listę (`JOBS_LIST_QUERY_ROOT`). Harness
    `/preview/champion-workspace` musi zasiewać ten klucz — sieć ma odciętą.
  - Kolumna kosztuje szerokość: na laptopie 1280 px z rozwiniętym menu
    „Rekrutacja” ma 204 px zamiast 293 (pomiar 13.10.2026, bez poziomego
    przewijania, wysokość wierszy bez zmian). Nie poszerzaj jej plakietek.
- **Lista nazw klienta jest tu szersza niż na stronie kariery.** Reguły
  kwot, kontaktów i znaków niewidocznych są wspólne (13.10.2026), ale nazwa
  wyświetlana i prawna klienta (`client_lint_names`) działa tylko
  w ogłoszeniu: na stronie kariery obróciłaby adresy `/r/<slug>` rozesłanych
  już linków i zaczęła odmawiać zatwierdzonym opisom — to osobna decyzja.

## Poprawki po audycie 13.10.2026 (14.10.2026)

- **Liczba przy słowie o wynagrodzeniu blokuje kopiowanie** (decyzja Artura
  „A”). „Budżet klienta: 25 000”, „Widełki 20–25k”, „Wynagrodzenie do
  18000”, „Salary up to 25k” bez waluty dawały tylko uwagę, a strona kariery
  to samo zdanie blokowała. Wzorzec jest jeden:
  `public_profile_lint.PAY_WORD_MONEY_PATTERN` (te słowa plus „pensja”
  i „zarobki”, liczba z co najmniej dwiema cyframi do pięciu słów dalej),
  a `job_ad/lint.py` traktuje jego trafienie jak pewną kwotę. Liczba przy
  „stawka”/„rate” zostaje uwagą. Koszt świadomy: „moduł wynagrodzeń dla
  10 tys. pracowników” też blokuje — komunikat dopowiada wtedy „Jeśli to nie
  kwota, napisz zdanie bez liczby przy tym słowie”. Angielskie „budget”,
  „pay” i „compensation” nie są na liście.
- **Numer punktu nie zjada liczby.** `generate._BULLET` zdejmuje „1.” i „2)”
  tylko wtedy, gdy nie stoi za nimi cyfra. Wcześniej „3.5 roku” zapisywało
  się jako „5 roku”, „2.5+ years” jako „5+ years”, „10.000” jako „000” —
  także przy ręcznej poprawce, bo `PUT` czyści treść tą samą funkcją.
- **Istniejące ogłoszenie zastępuje się tylko z wersją z ekranu.**
  `POST …/generate` bez `expected_updated_at` przy istniejącym ogłoszeniu =
  409 `job_ad_changed` („Ktoś w międzyczasie przygotował to ogłoszenie…”),
  zanim zawoła model. Okno, które nie widziało ogłoszenia, wysyła przy
  pierwszym „Przygotuj” pustą wersję; serwer nadpisywał wtedy treść
  poprawioną przez drugą osobę. Okno po 409 wczytuje ogłoszenie (test
  `fix48-ws09-first-prepare-conflict`). `PUT` bez wersji nadal przechodzi —
  edytować da się tylko ogłoszenie, które okno ma na ekranie.
- **Rekrutacji z ogłoszeniem oznaczonym jako wiszące nie da się usunąć.**
  `DELETE /api/jobs/{id}` przy aktywnym wierszu `job_ad_publications`
  (`removed_at IS NULL`) = 409 `job_has_ad_on_portal` z listą `portals`.
  Kaskada kasowała jedyny ślad, gdzie wisi ogłoszenie, którego NEXUS nie
  zdejmie. Po „Zdjęte z portalu” rekrutację da się usunąć.
