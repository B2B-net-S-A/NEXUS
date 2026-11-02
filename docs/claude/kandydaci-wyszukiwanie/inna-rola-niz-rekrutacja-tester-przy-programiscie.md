# Inna rola niż rekrutacja — tester przy programiście (27.10.2026)
<!-- indeks: `services/role_family.py`, `role_mismatch` w `proposal-facts`, plakietka „Inna rola”, „musi mieć X/Y”, nocny przegląd i pula „Nowych” bez innej roli poniżej 80% must -->

Zgłoszenie Delivery Leada: okno „Kandydaci do dodania” proponowało Senior QA
Automation Engineera do „Full Stack Developer (Java, Angular)” z 77%, a osobę,
która w NEXUSIE miała same rekrutacje testerskie, z 76%. Pomiar na kopii
produkcji (rekrutacja 758736): najlepszy fullstack z 9/10 „musi mieć” miał 81%,
tester z 4/10 — 71%. „Dop.” to w ~80% podobieństwo tekstu CV (66,7 z 83 pkt,
krzywa `sim^0.6`), wymagania ważą ok. 11 pkt, a słowa roli są celowo wycinane
z tytułu rekrutacji (`scoring_service._strip_role_words`), więc nic nie
porównywało zawodu osoby z zawodem rekrutacji. Decyzja Artura 27.10.2026:
oznaczyć inną rolę i pokazać „musi mieć X/Y”; wag „Dop.” nie ruszamy (zmienia je
Head of Recruitment w panelu, po pomiarze).

## Reguły

- **Rodzina roli** (`role_family.family_of`, bez AI): programista, tester,
  analityk, PM / Scrum, DevOps / admin, dane / BI, projektant UX/UI. Kolejność
  reguł ma znaczenie: „Software Developer in Test” to tester, „Data Analyst” to
  dane. Samo „IT Analyst” / „Analityk” i „Architekt” zostają nieznane (w
  zamówieniach Nordei „IT Analyst” bywa rolą techniczną). Tytuł mieszany
  z PM / Product Ownerem albo programista + analityk = nieznany.
- **Rola osoby:** `cv_extracted_data.current_position`, bez niego tytuł z wiersza
  okna. Historia w NEXUSIE (ostatnie 10 rekrutacji, bez unieważnionych i bez kart
  scrapera) wygrywa z CV, gdy jest wyraźna: ≥ 3 rozpoznane i ≥ 75% jednej rodziny.
- **Nie oznaczamy** przy roli nieznanej po którejkolwiek stronie, tej samej
  albo pokrewnej (programista ↔ DevOps / dane, analityk ↔ dane / PM). Lepiej brak
  znaku niż zły znak.
- **Okno** (`AddCandidatesPanel`, pole `role_mismatch` z
  `GET /api/jobs/{id}/proposal-facts`): plakietka „Inna rola: tester” z powodem,
  przekreślony procent, osoba zawsze pod osobami z roli rekrutacji (obie
  kolejności). Nikt nie znika z listy: przejście z QA do programowania bywa
  prawdziwe.
- **„musi mieć X/Y”** pod procentem w każdym wierszu propozycji — z wymagań
  zapisanych przy propozycji; połowa i mniej w tonie ostrzeżenia.
- **Nocny przegląd** (`auto_full_review.publish_run_proposals`) i pula
  dopełniania „Nowych” (`refresh_autofill_pool`) pomijają osobę z inną rolą,
  chyba że spełnia ≥ 80% „musi mieć” (`KEEP_MUST_SHARE`). Propozycje opublikowane
  wcześniej zostają i dostają oznaczenie w oknie. Propozycje scrapera ogłoszeń
  (`job_board`) i nowych CV (`new_cv`) tylko oznaczamy.
- **Skala w dniu wdrożenia** (staging z 22.10.2026): 1 254 z 31 077 otwartych
  propozycji z oznaczeniem, 271 z nich zostałoby mimo to (≥ 80% must). Na
  historii: 154 z 10 016 par „zweryfikowany / wysłany / zatrudniony” z ostatnich
  18 miesięcy (1,5%) dostałoby oznaczenie — to osoby, które zespół przyjął mimo
  innej roli, dlatego okno tylko oznacza i przesuwa, a nie ukrywa. Zmiana
  reguł klasyfikatora = ten sam pomiar przed i po.

## Dopisek 29.10.2026 — DevSecOps i pula „Nowych” bez wyjątku

Zgłoszenie rekrutera: w „Nowych” rekrutacji „DevSecOps - inżynier (ZOB-3104)”
karta „Od systemu · 68%” z analitykiem systemowym / architektem. Dwie przyczyny:
słowo „DevSecOps” nie zawiera „devops”, więc rekrutacja nie miała rodziny
i nic nie porównywało ról; a nawet z rodziną osoba przeszłaby wyjątkiem 80%,
bo lista technologii w CV architekta dała 7 z 8 „musi mieć” (same narzędzia:
GitLab CI, OpenShift, Argo CD, Docker, Kubernetes…). Decyzja Artura 29.10.2026:

- **DevOps** rozpoznaje też „DevSecOps”, „Dev-Ops”, „SecOps”.
- **Pula dopełniania „Nowych”** (`refresh_autofill_pool`) pomija każdą osobę
  z inną rolą, bez wyjątku `KEEP_MUST_SHARE`: karta stamtąd ląduje na
  tablicy bez człowieka. Wyjątek 80% zostaje tylko dla propozycji nocnego
  przeglądu (okno, z plakietką „Inna rola”), gdzie decyduje rekruter.
- **Historia roli** pomija karty wstawione przez dopełnianie „Nowych”
  (`entry_source = "system"`), tak jak karty scrapera — inaczej silnik
  utwierdzałby się we własnych wyborach.
- **Skala** (pula z produkcji 29.10.2026, 22 916 wierszy w 159 rekrutacjach):
  844 wiersze z inną rolą w 60 rekrutacjach odpadają przy następnym
  przeglądzie, 232 z nich przechodziły dotąd wyjątkiem 80% (najczęściej
  tester → programista 102, analityk → programista 38). Karty już wstawione
  do „Nowych” zostają.

## Dopisek 02.11.2026 — pula dobiera dalej po odrzuceniu innej roli

`refresh_autofill_pool` brał 150 najlepszych wierszy i dopiero z nich odrzucał
inną rolę, więc tam, gdzie czołówkę zajmowała inna rola, pula wychodziła mała
przy ok. 65 tys. ocenionych osób: „Python Developer” (115928) 13 osób, „Ferryt
Developer” (240915) 67, „UX Researcher” (749972) 75, UX Designer (115932) 99.
Silnik trzymający „Nowych” na 20 nie miał z czego dobierać. Reguła z 29.10
zostaje: inna rola nie wchodzi, ale jej miejsce zajmują kolejni, paczkami
(`_POOL_PAGE` = 500), aż będzie `AUTOFILL_POOL_SIZE` albo skończy się
`AUTOFILL_POOL_SCAN_LIMIT` (5000 przeglądanych wierszy).

- **Staging (kopia z 02.11.2026):** wszystkie cztery mają 150 osób; ostatnia
  osoba stała na miejscu 754 / 401 / 320 / 231 przeglądu, odczyt do 0,7 s.
  Wynik ostatniej osoby względem dawnej: 65,6 wobec 68,0; 59,6 wobec 60,8;
  67,4 wobec 68,3; 65,9 wobec 66,5.
- **Rozpoznanie roli:** tytuły czterech rekrutacji są rozpoznane dobrze, a odsiew
  jest prawdziwy: w 115928 wśród 754 przejrzanych 604 to inna rola, z tego 591
  testerów (m.in. „Test Automation Engineer”, „Software Developer in Test”).
  Złe oznaczenia to tytuły mieszane nazywające też rolę rekrutacji, np. „UX
  Designer / Business Analyst” — pojedyncze sztuki na rekrutację.
- **Migawka „Wysłani”** (`sent_vs_system`) czyta pulę bez zmian. Osoby, które
  były poniżej dawnego ucięcia, dostają teraz miejsce w puli zamiast „Poniżej
  puli 150”. Pule odświeżają się z przeglądami (48 na noc), więc przez pierwsze
  noce po wdrożeniu migawki mieszają obie głębokości.

## Dopisek 03.11.2026 — tytuł mieszany nazywający też rolę rekrutacji

`family_of` zwraca jedną rodzinę, więc „UX Designer / Business Analyst” przy
rekrutacji UX wychodził jako analityk, a „Junior Python Developer / Junior QA
Automation Tester” przy Pythonie jako tester. `role_mismatch` nie oznacza już
osoby, której tytuł z CV nazywa rolę rekrutacji osobną częścią.

- **Części** rozdzielają `/ | & , + ;` i spójniki. Myślnik nie rozdziela
  („Software Engineer - QA Automation” to jedna rola).
- **Nie liczy się jako rola:** część z jednego słowa („Senior Test
  Engineer/Developer”, „Manual Tester, UX”), część ze słowem „test” przy innej
  rodzinie niż tester („Test Developer”, „Test Platform Engineer”) i programista
  bez nazwy roli („Tech Lead”, „Backend Quality”).
- **Bez zmian:** `family_of` dla rekrutacji i historii. Wyraźna historia dalej
  wygrywa z CV także przy tytule mieszanym („Tester manualny | UX/UI Designer”
  z 9 z 10 rekrutacji testerskich zostaje oznaczony).
- **Cena:** kilka osób z „QA Engineer / Software Engineer” przy programiście traci
  oznaczenie, bo tytuł nazywa obie role. Zasada ta sama co wyżej: lepiej brak
  znaku niż zły znak.
- **Pomiar przed i po (kopia z 02.11.2026):** otwarte propozycje 1 264 → 1 253
  z 50 442 oznaczonych, w tym z ≥ 80% must 422 → 418; historia 154 → 153 z 13 815
  par „zweryfikowany / wysłany / zatrudniony”; pule 59 rekrutacji: 12 nowych osób
  (UX Designer 6, UX Researcher 2, Python Developer 4), 3 nowe osoby w 20 kartach.
  Żadne oznaczenie nie doszło.

## Rola nieznana w 20 kartach „Nowych” (pomiar 03.11.2026)

Reguła „nieznana rola = bez oznaczenia” zostaje. Po sięgnięciu puli głębiej
(02.11) sprawdzone, ile takich osób dochodzi do kart: `ranked_picks` + `_by_rules`
+ `_allowed`, 36 rekrutacji w pracy z rozpoznaną rolą.

- **Udział:** 111 z 720 kart (15,4%), przy dawnej puli 114 z 706 (16,1%). Na
  prawdziwych kartach z 23.10–02.11 tyle samo: 312 z 1 977 (15,8%). Głębsza pula
  nie podniosła udziału, ale skupia się on w kilku rekrutacjach („Ferryt Developer”
  14 z 20, „Python Developer” 7 z 20 wobec 3).
- **Kto to:** większość pasuje, tylko klasyfikator nie zna tytułu („Senior Android
  Engineer”, „Python Engineer”, „Release Manager” przy PM). Wyraźnie nie ta rola:
  ok. 25 ze 112 (ręczna ocena tytułów).
- **Los kart:** z tkniętych przez rekrutera dalej poszło 37 z 200 przy tej samej lub
  pokrewnej roli (18,5%), 5 z 41 przy nieznanej (12,2%), 0 z 9 przy innej. 88% kart
  nietkniętych, więc to dane z 10 dni, nie wyrok.
