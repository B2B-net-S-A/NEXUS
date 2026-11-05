# Pytania pod CV w „Ściądze do rozmowy” (05.11.2026)
<!-- indeks: „Dopytaj pod CV”, mapa must-have × role w kodzie, F44, odpowiedź w notatce z nazwą firmy, tylko Nowi i Screening -->

Decyzja Artura z 05.11.2026 (makiety: https://claude.ai/artifact/VWgK36R9QCvLa1E96birYX, wariant 3).
Luki wychodziły dopiero w QC, po wygenerowaniu CV: w ostatnich przebiegach od 15.10 476 z 820
par miało uwagę „Luka kandydata”, 1505 uwag łącznie. Sama reguła w prompcie nie podnosi liczby
wymagań w opisach ról (pomiar 02.11: 70 wobec 76, pliki rekruterów 85, na 175 wymagań), a fakt
z rozmowy z nazwą firmy tak: w próbie na jednej osobie Kafka Streams i Connect stały w opisie
roli w 2 z 2 biegów, bez notatek w 0 z 2.

- **Sekcja „Dopytaj pod CV” stoi w istniejącej ściądze** (`CvCallQuestions`, `DockCallCheatsheet`):
  w doku osoby i w zakładce „Po ludzku” podglądu. Działa też, gdy reszta ściągi jest pusta.
  Ściąga bez `candidateId` jej nie pokazuje.
- **Nic nie blokuje.** Pytania są opcjonalne, nie liczą się do minimum screeningu ani do
  przekazania. Formularz screeningu się nie zmienia (decyzja: wariant ze ściągą, nie karta
  w formularzu), a rekruter wpisuje odpowiedź w notatce i podaje nazwę firmy. Bez firmy generator
  nie przeniesie faktu do roli (`generator-cv/silnik-cv-bez-wypelniacza.md`).
- **Mapę liczy kod, pytania układa model.** `services/cv_call_questions.requirement_map` porównuje
  must-have z rolami przez `dz_review.found_in`, tą samą metodą co QC. Stany: `opisane`, `tylko_lista`,
  `brak_w_rolach`, `brak`, a rola bez opisu to `unverified`. Dopasowanie po słowach może nie znaleźć
  wymagania opisanego innymi słowami, dlatego pytanie jest otwarte i niczego nie przesądza. Najpierw
  umiejętności krytyczne.
- **Do modelu idą tylko luki i stanowiska** (firma, nazwa, opis, technologie), bez nazwiska,
  kontaktu, stawek i notatek. F44 `cv_call_questions`, Sonnet 5.5 z Sonnet 5, w `ai_feature()`.
  Próba na 5 osobach: 3–14 s.
- **Co wolno pokazać** (`parse_questions`): wymaganie z listy luk, firma z ról, stan z mapy, nie
  z modelu. Pytanie z formą zależną od płci („miałeś/aś”, „używałeś”), o stawkę albo dostępność
  odpada. Zepsuta odpowiedź modelu daje stan `failed` z „Ponów”, nie pustą listę.
- **Tylko otwarta rekrutacja i etap „Nowi” albo „Screening”** najnowszego wiersza pary. Dalej
  `not_applicable` i bez wywołania modelu. Bez Championa `no_requirements`, bez CV `no_cv`: sekcji nie ma.
- **GET nic nie zapisuje, nie woła modelu i nie pobiera pliku CV.** Odcisk (`inputs_hash`) liczy się
  z sumy pliku w migawce etapu, odczytu ról i listy must-have. Front prosi o pytania raz na
  zamontowanie, gdy ich nie ma albo odcisk się zmienił. Po `failed` bez zmiany źródeł czeka na „Ponów”.
  `POST …/refresh` z limitem, w `READ_ONLY_POST_ROUTE_TEMPLATES`, 403 w „podglądzie jako”.
- **Tabela `cv_call_questions` ma klucz (osoba, rekrutacja), nie wiersz etapu**, bo każdy ruch karty
  zakłada nowy wiersz `candidate_stages`. To pamięć podręczna, usunięcie osoby albo rekrutacji ją kasuje.
- **Pytanie znika, gdy padła odpowiedź:** wymaganie w odpowiedziach screeningu (`cv_qc.answers_text`)
  albo w „Potwierdzone z kandydatem”. Odpowiedź przecząca nie gasi pytania, bo `answers_text` zdejmuje
  zdania przeczące. Sama notatka bez potwierdzenia też go nie gasi.
- **Poza zakresem:** karta z polami odpowiedzi w formularzu (wariant 1) i mapa w „Wymaganiach”
  (wariant 2) odrzucone na rzecz ściągi. Przy osobie bez opisów ról w odczycie (28% wierszy w QC)
  większość wymagań ma stan `brak` albo `brak_w_rolach`.
- Testy: `test_cv_call_questions.py`, `test_cv_call_questions_api.py`, `CvCallQuestions.test.tsx`.
