# Odczyt maila: propozycja krytycznych, technologie z maila, wyliczanki i cechy (07.11.2026)

Decyzja Artura z 07.11.2026 („rób wszystko”, makiety M1, M2, M4 i M5 w
https://claude.ai/artifact/U5xPzXiKJXixweYv5M8v7n). Pomiar na pięciu
prawdziwych requestach: po odczycie Delivery Lead od zera wybierał krytyczne
(53 z 68 rekrutacji od 15.10), dopisywał technologie, które stały w mailu,
rozdzielał wyliczanki złączone przez „lub” i usuwał cechy wpisane jako
„musi mieć”.

Kod: `services/intake_requirements_refine.py`, podpięty w
`job_request_intake.read_request` (`refine_rows` po odczycie modelu,
`with_proposals` po `apply_people_reach`). Bez modelu i bez zmiany promptu:
słownik w pamięci i tekst maila.

- **M4: jedna technologia na wiersz.** Wiersz z kilkoma różnymi hasłami
  słownika rozpada się na osobne wiersze tego samego poziomu, chyba że mail
  podaje je jako zamienniki (`lub`, `albo`, `or`, `/` w odległości do 60 znaków)
  albo hasła są z jednej rodziny (wspólne pierwsze słowo, „wynika z”). Uwaga
  w „Uwagach z odczytu”. 789180: „MongoDB | CosmosDB | Elasticsearch” = 8 262
  osoby, sam CosmosDB 167.
- **M5: cechy osoby do rozmowy.** Wiersz z samych cech (`TRAIT_PHRASES`:
  drive, resilient, structured, decision making… albo `read_phrase` = soft)
  idzie do „Rekruter sprawdza w rozmowie”. Tylko całe słowo albo fraza, więc
  „Google Drive” zostaje.
- **M1: propozycja krytycznych** (`critical_proposal`). Wiersze „musi mieć”,
  przy których klient podaje co najmniej 3 lata (lata najbliżej nazwy
  w zdaniu), od największej liczby, najwyżej 3. Bez takich zdań: technologie
  z nazwy stanowiska, najwyżej 2. Tylko technologia ze słownika (także hasło
  wewnątrz frazy z maila: „Microsoft Dynamics 365 CE/CRM”). Formularz pokazuje
  propozycję z cytatem i trzema decyzjami: „Zatwierdź krytyczne”, „Brak
  krytycznych”, „Wybiorę sam”. **Nic nie zapisuje się samo**: krytyczne dalej
  wybiera Delivery Lead (zasada z 30.09.2026), a wymóg decyzji przy przekazaniu
  zostaje.
- **M2: „W mailu są też”** (`mail_technologies`). Hasła słownika ze znaleziskiem
  w mailu, których nie ma w żadnym wierszu (także jako hasło wewnątrz słowa
  wiersza), najwyżej 12. Kolejność: technologie z CV, potem narzędzia
  i standardy, na końcu praktyki; w grupie kolejność z maila. Pomija role,
  słowa „jest” i „go” oraz nazwę wewnątrz dłuższej nazwy („Apache” w „Apache
  Kafka”). Klik dodaje wiersz „mile widziane”; „Dodaj wszystkie” — wszystkie
  w limicie listy.
- Pola formularza: `criticalProposal`, `mailTechnologies` (`IntakeForm`),
  przychodzą razem z wierszami odczytu (`job-intake-fill`), panel
  `components/v2/jobs/new/IntakeRequirementProposals.tsx`.
- Pomiar 07.11 (staging, model z produkcji): propozycja krytycznych = wybór DL
  w 3 z 4 rekrutacji, w których DL je wybrał; „W mailu są też” podsuwa 10
  z technologii, które DL dopisał ręcznie (789180: 4, 789198: 5, 789191: 1).
