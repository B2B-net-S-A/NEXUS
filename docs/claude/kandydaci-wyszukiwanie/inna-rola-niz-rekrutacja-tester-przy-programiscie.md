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
