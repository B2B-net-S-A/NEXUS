# Zakładka „Wnioski” w Insights: co się powtarza i decyzja człowieka
<!-- indeks: reguły w kodzie bez AI, „Tak” niczego nie włącza, „Nie teraz” 30 dni, „Nie” do dwukrotnego wzrostu, najwyżej 5 spraw, odczyt opisów „Szacunek”, cechy chronione poza cytatami, ocena na 100 dodanych, tabela insight_decisions -->

Decyzje Artura z 04.11.2026 (makieta: https://claude.ai/artifact/9adc6FGa17t5PzJFxDfiJB).
NEXUS ma się uczyć z decyzji zespołu i klientów bez dodatkowego klikania: jedno miejsce
zbiera wnioski z danych, które już są, a człowiek decyduje.

Kod: `api/insights_wnioski.py`, `services/insights_wnioski.py`, tabela `insight_decisions`
(0646, DDL w `services/insight_decisions_schema.py`, lustro w `entrypoint.sh`, sonda
w `/api/health/deep`), front `components/insights/views/WnioskiView.tsx`,
`sections/WnioskiPeoplePanel.tsx`.

- **Miejsce:** zakładka między „Źródła” a „Raporty”, cztery części: „Do decyzji”, „Powody
  odrzuceń”, „Co zbieramy”, „Historia decyzji”. Licznik spraw przy nazwie.
- **Dostęp:** admin i Head of Recruitment, bramka także na serwerze (`VIEWER_ROLES`, lustro
  `RHYTHM_ROLES`). Sprawa z właścicielem „Administrator” przyjmuje decyzję tylko od admina;
  ta reguła siedzi w handlerze, więc ma własny test, a nie wiersz we wzorcu.
- **„Tak” zapisuje decyzję i nie zmienia działania systemu.** Zmiana przechodzi zwykłą
  drogą: PR, wdrożenie w oknie, ocena po 30 dniach. Dlatego przycisk mówi „zleć”, nie „włącz”.
  „Nie teraz” chowa na 30 dni. „Nie” chowa, dopóki liczba nie wzrośnie dwukrotnie względem
  `count_at_decision`. Wiersz na każde kliknięcie, nic się nie nadpisuje: stan to ostatni
  wiersz, reszta to historia.
- **Stały zestaw reguł w kodzie, bez modelu AI i bez pętli w lifespanie.** Sprawy liczą się
  przy odczycie, cache 5 min, decyzje zawsze na świeżo. Ekran pisze „Dane na dziś”, nie
  „Liczone co noc”, bo nocą nic tu nie biegnie. Najwyżej 5 otwartych spraw, od najważniejszej;
  poniżej progu próby sprawa nie jest otwarta. Nowa sprawa = reguła w `compute_cases`
  i wpis w `CASE_COPY`.
- **Okno: od 12.10, a po 90 dniach okno się przesuwa** (`counted_from`). Powody odrzuceń są
  w NEXUSIE dopiero od 12.10.2026, więc ekran nie pisze „90 dni”. Bez przesuwania „Nie”
  wracałoby samo, bo liczba rośnie z czasem.
- **Odczyt opisów „Inne” to szacunek.** Słowa kluczowe w `_READ_CASE`, liczone przy odczycie,
  niezapisywane. Ręczne sprawdzenie 90 wpisów dało ok. 90% trafności: to dolna jakość, nie
  prawda. Oryginalne wpisy zostają nietknięte. Każda liczba z odczytu ma etykietę „Szacunek”.
- **Cechy chronione nigdy nie stają się wnioskiem ani regułą.** Opis ze słowami o narodowości,
  wieku, zdrowiu albo ciąży (`PROTECTED_RE`) liczy się jako „Nieodczytane”, nie trafia do
  cytatów, przykładów ani licznika „Powtarza się”. Lista jest szeroka, bo fałszywe trafienie
  tylko chowa przykład. Tej zakładce nie wolno też przekazywać takich opisów do modelu.
- **Żadnych miar per osoba z zespołu** (decyzja o PIP): tylko klienci, rekrutacje i typy
  sygnałów. Powiadomienia liczymy po typie, nie po osobie. Na ekranie liczby bez nazwisk,
  osoby tylko po kliknięciu i z `CandidatePIIAccess`, jak w „Źródłach”. Lista nie niesie
  treści opisu. Liczba i lista to ten sam SQL (`_CLASSIFIED`).
- **Wniosek nie sugeruje wstrzymania CV.** W rekrutacji 42511 po piątej takiej odmowie 3 osoby
  poszły dalej. Wiersz „Powtarza się” z etapu 2 ma informować i niczego nie blokować.
- **Reguły ocenia się na 100 dodanych osób i na kartach w tym samym wieku (3 dni).** Sam udział
  myli: „Za drogo” spadło z 38% do 10% odrzuceń, a na 100 dodanych to 0,9 i 1,1, bo ludzie
  zaczęli częściej odrzucać. Werdykt dopiero po 30 dniach (`rule_verdict`, od 200 dodanych
  w każdej grupie, poprawa od 25%). Procent dopasowania się tu nie zmienia.
- **Historia:** decyzje z zakładki, dwie zatwierdzone 04.11.2026 poza nią (`APPROVED_AT_LAUNCH`:
  zatrudnieni gdzie indziej z #3034 i nowe powody w oknie, liczby z tamtego dnia) oraz reguły
  z października z nagłówka `services/new_column_autofill.py`.
- **Poza etapem 1:** wiersz „Powtarza się” na Tablicy i usunięcie kciuków to etap 2, przykłady
  poprawek CV z propozycją instrukcji to etap 3, pierwszy z modelem. Procent dopasowania,
  „Zgłoś uwagę” i propozycje wag: poza planem.
- **Pasek zakładek:** przy 1280 px pasek admina przechodził pod nagłówek i zabierał ok. 45 px,
  dlatego zakładka aktywności nazywa się tam „Aktywność”. Pełna nazwa zostaje na ekranie.
- **Awaria nie wygląda jak pusta lista:** „Nic nie czeka” tylko po udanym odczycie, błąd zapisu
  przez `apiErrorMessage`, a „Tak” i „Nie” potwierdza `useConfirmV2()`, bo decyzji się nie cofa.
