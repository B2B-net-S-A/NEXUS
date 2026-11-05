# Wiersze „musi mieć”, których nie ma nikt z wysłanych (02.11.2026)
<!-- indeks: ostrzeżenie pod wierszem, „Podpowiedz słowa” (F41), powód `no_sent_match` w propozycji i na pulpicie, od 3 wysłanych z CV -->

Decyzja Artura z 02.11.2026, raport i makiety: https://claude.ai/artifact/EHzqs9fXxjfrwjDgfZ8bwj.

Pomiar na kopii z 02.11 (kod z #2882, słownik wczytany): w 55 otwartych rekrutacjach
142 z 1033 wierszy nie ma według silnika nikt z co najmniej 3 wysłanych. Model
czytający CV znajduje je u co najmniej połowy tylko w 35 przypadkach, a w 74 też
ich nie znajduje, w tym w 54 przy konkretnych technologiach. To więc częściej
wymaganie przesadzone niż błąd odczytu, a nie sposób na obniżenie fałszywych braków:
19,8% w tych wierszach wobec 23,6% w pozostałych.

- **Co liczy.** `services/requirement_sent_gaps.compute` bierze osoby z `candidate_stages`
  na etapach `SENT_STAGES` (lustro `api.jobs.SENT_TO_CLIENT_STAGES`), tylko z tekstem CV,
  i czyta wiersze przez `evaluate_requirements`, więc znaczy to samo co „musi mieć X/Y”.
  `interview` to rozmowa wewnętrzna przed wysyłką, nie wysłany. Poniżej 3 osób nic nie mówimy.
  Wiersz ze starą technologią (`stale_profile_signal`) i potwierdzony przez rekrutera
  (`load_verified_requirements`) nie jest brakiem.
- **Awaria to brak ostrzeżenia, nie „nie ma nikt”.** `attach_gate_evidence` połyka błąd
  odczytu notatek, a ocena bez dowodu nie czyta CV, więc każdy wiersz wyszedłby brakiem.
  `compute` rzuca wtedy `EvidenceUnavailable`, a pamięć procesu niczego nie zapisuje.
- **Ostrzeżenie pyta, nie zmienia.** `SentGapCallout` pod wierszem zastępuje ostrzeżenie
  o rzadkim słowie: „Do rozmowy”, „Zostaw” i „Podpowiedz słowa”. Krytycznych w propozycji
  nie ruszamy. Do rozmowy, nie do opisu, bo listę „Rekruter sprawdza w rozmowie” rekruter
  widzi w formularzu screeningu, a opisu nikt nie odhacza. Serwer oddaje zapisane słowa
  wiersza (`with_saved_words`): słowo dopisane w edytorze chowa ostrzeżenie do zapisu.
- **Słowa (F41, `requirement_word_hints`).** Tylko po kliknięciu i bez zapisu: model czyta
  do 6 CV, a kod zostawia najwyżej 3 słowa, które silnik naprawdę znajduje u co najmniej
  2 wysłanych. Słowo z jednego CV to nie wzorzec. Słowa zostają w pisowni z CV, bo „QA”
  i „Go” silnik szuka z wielkością liter. Pomiar: 33 z 70 takich słów ma ponad 3 000 osób
  w bazie, więc przycisk pokazuje liczbę osób, a decyzja należy do Delivery Leada.
  Awaria modelu to `available: false`, ostrzeżenie działa dalej.
- **Propozycja i pulpit.** Powód `no_sent_match` w `requirement_cleanup.build_proposal`
  przenosi wiersze do rozmowy po „Zatwierdź”; rekrutacja nie traci ostatniego słowa do
  szukania. Tak ostrzeżenie dosięga profili na starych polach bez edytora wierszy (82 ze 142).
  Wynik czyta z pamięci procesu po odcisku profilu, jak liczby osób przy `rare_word`:
  pulpit nie czyta CV w żądaniu. Dolicza go pętla `requirement_row_counts`, pulpit
  sam tylko brakujące w limicie 1,5 s. Średnio 0,11 s na rekrutację.
- **Stary profil bez wierszy (05.11.2026, decyzja Artura).** Sama propozycja to za mało: mówi
  jednym ogólnym zdaniem i wymaga przyjęcia całej zmiany, a na rekrutacji 454615 serwer zwracał
  2 wiersze i edytor nie pokazywał żadnego. `StackSentGaps` pokazuje to samo ostrzeżenie pod „Musi mieć”, z tymi samymi
  akcjami: „Do rozmowy” zdejmuje pozycję z „Musi mieć”, wierszy wyszukiwania i krytycznych, a słowo
  z podpowiedzi dochodzi jako wariant „A lub B”. Propozycja i „Uprość do słów kluczowych” zostają.
- **Pomiar z modułami dopasowania poza lifespanem** musi wywołać `refresh_alias_map`:
  bez słownika `k8s` nie łączy się z Kubernetesem, a fałszywe braki wychodzą 24,5% zamiast 22,8%.
