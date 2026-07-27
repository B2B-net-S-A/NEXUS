# Programy Codexa — co było w planach, co zrobiono, co zostało

**Stan na:** 2026-07-20 · **Produkcja:** `bdf5a75`, healthy · **Źródło:** 12 dokumentów-planów z 15–17.07 + weryfikacja w gicie i w kodzie

---

## Jak czytać ten dokument

Codex (drugi asystent) przeprowadził w dniach 15–17 lipca serię audytów NEXUS-a — moduł po module. Każdy audyt kończył się planem naprawy rozbitym na małe, odwracalne paczki zmian (PR-y). Ten dokument tłumaczy każdy z tych planów na zwykły polski i pokazuje, co z niego faktycznie weszło do systemu.

**Skróty, które będą się powtarzać:**

| Skrót | Co znaczy |
|---|---|
| **PR** | Pull request — jedna zamknięta paczka zmian, osobno zatwierdzana i wdrażana |
| **P0 / P1 / P2** | Priorytet: P0 = krytyczne (bezpieczeństwo, utrata danych), P1 = poważne, P2 = dług techniczny |
| **containment** | „Zatamowanie krwawienia" — łatka zamykająca dziurę, bez przebudowy |
| **RBAC** | Kto co może zobaczyć i zmienić (uprawnienia per rola) |
| **IDOR** | Podmieniasz numer w adresie URL i widzisz cudze dane |
| **SSRF** | Zmuszasz serwer, żeby pobrał coś z sieci wewnętrznej firmy |
| **viewer / rola `user`** | Najniższa rola — konto tylko do podglądu, np. dla klienta |
| **shadow mode** | Nowy mechanizm liczy równolegle ze starym, ale użytkownik widzi stare wyniki |
| **cutover** | Moment przełączenia ze starego mechanizmu na nowy |

---

## 1. Skala w liczbach

| | |
|---|---|
| Dokumentów-planów od Codexa | **12** |
| Łącznie zaplanowanych PR-ów | **~295** |
| Zmergowanych PR-ów w piku (16–17.07) | **50** |
| Z tego realizujących plany Codexa | **~44** |
| PR-ów otwartych, niezmergowanych | **1** (#816 — patrz sekcja 14) |

**Wzorzec, który się powtórzył w każdym module:** wykonano *pierwszą falę* (containment — zamknięcie dziur bezpieczeństwa), a przebudowy architektoniczne świadomie odłożono lub odrzucono. To była dobra decyzja — ale oznacza, że system jest dziś *bezpieczniejszy*, a nie *naprawiony*.

**Motyw przewodni wszystkich audytów:** rola `user` (konto tylko-do-odczytu, m.in. dla klientów) miała dostęp do prawie wszystkiego — danych osobowych 54 tys. kandydatów, stawek, marż, faktur, nagrań rozmów, kalendarzy. To zostało zamknięte we wszystkich modułach.

---

## 2. Kalendarium — co się kiedy działo

| Kiedy | Co |
|---|---|
| **Śr 15.07** | Codex robi 3 pierwsze audyty (system, ręczne wyszukiwanie, AI matching) |
| **Czw 16.07, 08:56 – 23:36** | **Główny burst: 49 PR-ów.** Codex dostarcza 9 kolejnych planów, równolegle idzie implementacja containmentu w 7 modułach |
| **Czw 16.07, ~21:20** | Coolify (system wdrożeń) zaczyna zwracać błąd 500 na wszystko. Deploye stają |
| **Pt 17.07, rano** | **Pełna awaria — cała firma bez systemu.** Dysk serwera zapełniony w 98,8% od intensywnych przebudów |
| **Pt 17.07, ~12:23** | Awaria ugaszona. Pułapka po drodze: komenda czyszcząca skasowała bazę Coolify i kontenery aplikacji (dane ocalały) |
| **Pt 17.07, 14:23** | PR #811 — alerty zajętości dysku, żeby to się nie powtórzyło. **Jedyny PR piątku** |
| **Pt 17.07** | Trzy dodatkowe audyty „drugiego przebiegu" (M4, M6, matching) — szukające błędów w kodzie, który sami właśnie napisaliśmy |
| **Nd 19.07** | #812–#814 — poprawki logowania (wygasła sesja, callback SSO, logowanie tylko przez Microsoft). To reakcja na zgłoszenia, nie plany Codexa |
| **Pn 20.07** | #815 — regresja po containmencie: błąd 403 udawał pustą listę w generatorze B2B |

**Uwaga o „piątku":** główna praca wpadła w **czwartek 16.07**, ciągnąc się do 23:36. Piątek zszedł prawie w całości na gaszenie awarii, którą ten burst spowodował.

---

## 3. Moduł 2 — Kandydaci i baza talentów

**Plan:** 7 PR-ów · **Zrobione:** 1 · **Zostało:** 6

### Za co odpowiada
Serce systemu: wszystko, co dzieje się z kandydatem od wejścia do bazy aż do przypisania go do zlecenia. Wszystkie drogi wejścia (ręcznie, CV, formularz publiczny, LinkedIn, Traffit), rozpoznawanie duplikatów, profil, dokumenty, zgody RODO, pule talentów, wyszukiwanie. **W bazie: 54 096 kandydatów.**

### Co audyt znalazł (8 problemów krytycznych)

| ID | Co było zepsute | Co to znaczyło dla firmy |
|---|---|---|
| M2-SEC-01 | Konto tylko-do-odczytu mogło pobrać listę wszystkich 54 tys. kandydatów z e-mailami, telefonami, stawkami, NIP-ami i CV | **Każda osoba z dostępem podglądowym — w tym klient — mogła wyeksportować całą bazę talentów firmy.** Ukrycie przycisku nic nie dawało |
| M2-SEC-02 | To samo konto mogło jednym poleceniem „spseudonimizować" 500 kandydatów naraz | Nieodwracalne wyczyszczenie danych, bez potwierdzenia i bez śladu |
| M2-SEC-03 | Checkbox „Respektuj NDA / blacklist" — odznaczenie wyłączało sprawdzanie twardych zakazów | **Rekruter mógł nieświadomie zaproponować kandydata klientowi, któremu umownie nie wolno go pokazać** |
| M2-PRIV-01 | „Anonimizacja" zostawiała CV, dokumenty, doświadczenie, notatki, nagrania i wektory z nazwiskiem | Odpowiedź „usunęliśmy Pana dane" byłaby nieprawdą. Realne ryzyko kary RODO |
| M2-PRIV-02 | Twarde usunięcie kandydata niszczyło historię kontraktową, a pliki i wektory zostawały | Tracimy dowody rozliczeń, a dane osobowe i tak zostają |
| M2-PRIV-03/04 | Surowe CV z imieniem i nazwiskiem (do 8000 znaków) szło do zewnętrznych dostawców AI | Brak umów powierzenia danych, brak rejestru zgód |
| M2-INTAKE-01 | Ktokolwiek znający e-mail kandydata mógł przez publiczny formularz nadpisać mu CV i **przejąć jego profil na siebie** | Kradzież kandydata z bazy przez formularz |

Plus 20 problemów P1: różne rozpoznawanie duplikatów na każdej ścieżce, skrypt scalania kasujący całe tabele przy konflikcie, sześć równoległych miejsc na CV (kandydat z CV pokazywany jako „bez CV"), eksport CSV bez neutralizacji formuł (dane kandydata wykonują się jako formuła w Excelu), dziewięć pól odpowiadających na pytanie „czy wolno go pokazać", notatka gubiona przy dodawaniu kandydata, ekran porównania pokazujący **wymyślone procenty**.

### Co zrobiono
**PR 1/7 — [ZROBIONE, #774]** — wdrożony i zweryfikowany na produkcji. Rola `user` straciła cały moduł kandydatów. Eksport tylko dla TAC i wyżej, z zapisem w audycie. Masowa anonimizacja i twarde usuwanie **zablokowane komunikatem błędu** (409) do czasu zbudowania prawdziwego mechanizmu. Blokady NDA/blacklist egzekwowane zawsze po stronie serwera.

### Co zostało
| PR | Co miał zrobić | Blokada |
|---|---|---|
| PR 2 | Prawdziwy rejestr zgód RODO + mechanizm realnie wykonujący żądanie usunięcia + odcięcie wycieku CV do dostawców AI | **Wymaga zatwierdzonej przez DPO macierzy celów, podstaw prawnych i retencji** |
| PR 3 | Każde zgłoszenie ląduje jako osobny rekord, dopiero potem łączone z profilem (zamyka przejęcie profilu) | Po PR 2 |
| PR 4 | Rejestr tożsamości, bezpieczne scalanie duplikatów zamiast kasującego skryptu | Po PR 3 |
| PR 5 | Jedno miejsce na CV z wersjonowaniem, antywirus, bezpieczny eksport | Po PR 2/3/4 |
| PR 6 | Jedna odpowiedź „czy wolno użyć kandydata" + wyszukiwarka V3 | Po PR 2/4/5 |
| PR 7 | Poprawki interfejsu, wydajność, panel jakości danych | Ostatni |

### Co nadal jest otwarte i groźne
1. **Publiczny formularz nadal pozwala przejąć cudzy profil** po samej znajomości e-maila.
2. **Surowe CV z nazwiskiem nadal wychodzi do dostawców AI**, baza wektorowa nadal przechowuje nazwiska.
3. **System nie potrafi rzetelnie wykonać żądania usunięcia danych.** Do PR 2 każde takie żądanie trzeba obsłużyć ręcznie.

### Decyzja, która blokuje wszystko
**Zatwierdzona przez DPO macierz: w jakich celach, na jakiej podstawie prawnej i jak długo przechowujemy dane kandydatów.** Bez niej stoi PR 2, a bez PR 2 stoją PR 5 i 6 — czyli większość planu.

---

## 4. Moduł 3 — Dopasowywanie kandydatów do ofert (matching)

**Plan:** 18 PR-ów · **Zrobione:** 2 · **Odrzucone/odroczone decyzją:** 9 · **Zostało:** 7

### Za co odpowiada
Silnik, który bierze ofertę i wyszukuje w bazie pasujące osoby, wystawiając ocenę 0–100 z uzasadnieniem. Zasila marketplace, propozycje dla klienta i ręczne wyszukiwanie.

### Co audyt znalazł

**Bezpieczeństwo i koszt:**
- Konto tylko-do-odczytu mogło **przypisać kandydata do oferty** i uruchamiać płatne generacje AI.
- Endpoint `/ai-matches` przyjmował dowolny limit → jedno żądanie mogło wysłać **nieograniczoną liczbę CV do płatnego dostawcy zewnętrznego**.
- Gdy dostawca embeddingów padał, system przełączał się na model lokalny i **zapisywał jego wyniki do tej samej szuflady** — jak wrzucenie centymetrów do tabeli w calach. Podobieństwa stawały się losowe.
- Gdy baza wektorowa padała, zły wynik był zapisywany jako prawidłowy i **przeżywał powrót dostawcy**.

**Wynik nie znaczył tego, co pokazywał:**
- Siedem równoległych silników. Ta sama osoba miała `0,15` w jednym panelu i `66/100` w drugim.
- Wynik pokazywał 66,2, a widoczne warstwy sumowały się do 61,2 — **5 punktów brało się znikąd** (ukryty bonus historyczny).
- **Edytor wag miał 5 suwaków zamiast 6** — każdy zapis ustawiał wagę warstwy „Champion" na zero, czyli po cichu wyłączał dopasowanie do profilu idealnego klienta.
- Marketplace pokazywał 18 konsultantów i **prawie zero ofert dla nich** — system brał top-N ze wszystkich ofert (też szkiców i zamkniętych), a dopiero potem odsiewał opublikowane.
- Użytkownicy widzieli dosłowny tekst `(TODO)` i surowy błąd `query.current_user: Field required`.

### Co zrobiono
- **PR A — [ZROBIONE, #776]** — limity na kosztowne parametry, naprawa „Przelicz scoring" (nie działał — błąd 500), izolacja dostawców AI, brak zapisu do cache w trybie awaryjnym, pula podniesiona do 150 (łagodzi marketplace), uprawnienia.
- **PR B — [ZROBIONE, #778]** — wiersz „Historia +X pkt" w podpowiedzi (koniec z 5 punktami znikąd), **6 suwaków zamiast 5**, stara lista tylko dla admina, `(TODO)` zastąpione realną kontrolką „Min. dopasowanie", błędy przestały wyciekać treścią techniczną.

### Co świadomie odrzucono
- **PR 3–6** (wersjonowanie rankingu, telemetria V2, dane treningowe, ewaluator) — **wstrzymane**: budowanie wersji 2 na wyłączonej telemetrii wersji 1 to piętrzenie martwej infrastruktury.
- **PR 7 w części „brak danych = brak punktów"** — **odrzucone**: kłóci się z wcześniejszą decyzją, że scoring jest za surowy, a nie ma narzędzia do zmierzenia skutku zmiany.
- **PR 15–17** (jeden przycisk „Przypisz", platforma eksperymentów A/B, uczony ranker) — **przerost dla jednoosobowego zespołu**.

### Drugi przebieg audytu (17.07) — 13 nowych, potwierdzonych błędów

To jest najważniejsza część tego rozdziału, bo dotyczy rzeczy, których pierwszy audyt nie widział:

| ID | Co jest zepsute | Dlaczego to boli |
|---|---|---|
| **N-01** | Gdy do jednej oferty pasuje **dwóch lub więcej** kandydatów, drugie powiadomienie łamie regułę bazy, wyjątek wywraca cały skan i **wycofuje też pierwszy, poprawnie utworzony alert** | **To wyjaśnia, dlaczego marketplace „prawie nic nie znajduje".** Użytkownik nie widzi błędu — po prostu nie dostaje powiadomień. Mechanizm działa na żywo |
| **N-02** | Import z LinkedIna bierze etap procesu wprost z żądania, bez sprawdzania | Jednym żądaniem można oznaczyć kandydata jako `hired`/`rejected`, **omijając cały proces akceptacji i bramkę stawki** |
| **N-03** | Scoring zeruje wynik osoby z czarnej listy, ale zaraz potem dolicza bonus historyczny **bez sprawdzenia, czy była kara** | Zablokowany kandydat wraca na listę z dodatnim wynikiem i **aktywnym przyciskiem „Przypisz"**. Kontrolka „Min. dopasowanie", którą sami dodaliśmy w #778, pozwala rekruterowi zejść na tyle nisko, żeby go zobaczyć |
| **N-04…N-07** | Cache nie jest czyszczony, gdy zmienisz stawkę, lokalizację, tryb pracy, termin lub klienta oferty; sync z Traffitem i generator Champion też nie czyszczą ocen | **Zmieniasz stawkę w ofercie — system dalej pokazuje stare oceny.** Kandydat zablokowany po stronie Traffita zachowuje stary, niezerowy wynik |
| **N-08** | Ekran „szukam kontraktu" może wywołać **do 200 płatnych, seryjnych wywołań** bez limitera | Koszt |
| **N-12** | Migracja tabeli shortlisty nie ma odpowiednika w skrypcie startowym | Ryzyko błędu 500 na produkcji (patrz sekcja 15) |
| **N-13** | **9 plików testów matchingu wciąż jest poza obowiązkową bramką CI** — w tym te, które złapałyby N-01 i N-03 | Regresja przechodzi na zielonym świetle |

**Wniosek autora drugiego przebiegu:** N-01 i N-04/N-05 są prawdopodobnie **bardziej odczuwalne biznesowo niż cokolwiek z niezrealizowanej części planu głównego.**

---

## 5. Moduł 4 — Pipeline rekrutacyjny

**Plan:** 22 PR-y · **Zrobione:** 8 · **Zostało:** 14

### Za co odpowiada
Cała droga kandydata od przypięcia do zlecenia aż do rozpoczęcia pracy: etapy na tablicy Kanban, screening, stawki i ich zatwierdzanie, wysyłka profilu do klienta, rozmowy, oferta, kontrakt.

### Co audyt znalazł

**Fundamentalny problem (P0.1):** w systemie **nie istnieje obiekt „ten kandydat w tym zleceniu"**. Aktualny stan jest zgadywany z „najnowszego wpisu w historii", a różne części systemu inaczej definiują „najnowszy". Dlatego raport, tablica i profil mogą pokazywać trzy różne stany tej samej osoby.

| ID | Co było zepsute | Co to znaczyło |
|---|---|---|
| P0.5 | Budżet zlecenia jest miesięczny, kandydat może mieć stawkę godzinową — kod porównywał **surowe liczby bez przeliczenia** | „150 PLN/h < 25 000 PLN/mies." jest liczbowo prawdą, ale to nie jest decyzja budżetowa. **System przepuszczał kandydatów, których nie powinien** |
| P0.9 | Przycisk „Wyślij klientowi" generuje CV i kopiuje link — **nie zapisuje komu, jakiej wersji, po jakiej stawce i kiedy** | **Prawdopodobnie najdroższa luka.** Przy sporze z klientem („nie dostaliśmy go" / „stawka była inna") system nie potrafi udowodnić, co wysłaliście |
| P0.2 | Własny etap „Zatrudniony" może nie utworzyć kontraktu, własny „Odrzucony" może nie wysłać maila | Na produkcji zaimportowany etap „Lista rezerwowa" jest ustawiony jako terminalny „wycofany" — „wstrzymany do później" **znika z procesu** |
| P0.6 | Mail może wyjść **zanim** zmiana zostanie zapisana w bazie | Kandydat dostaje maila o czymś, czego w systemie nie ma |
| P0.8 | „Usuń z rekrutacji" trwale kasuje całą historię pary, razem z CV — a potrafi zostawić wiszący kontrakt | Bezpowrotna utrata dowodów jednym kliknięciem. Przycisk aktywny nawet na karcie osoby zatrudnionej |
| P0.10 | „Zatrudniony" tworzy tylko szkic kontraktu z datą startu ustawioną na dziś | Nie wiadomo, na jakie warunki kandydat się zgodził. **Raporty liczą sam etap jako obsadzenie → statystyki mogą być zawyżone** |
| P1.4 | Po błędzie karta zostaje w nowej kolumnie (w kodzie był komentarz „TODO: cofnij po błędzie") | **Użytkownik widzi stan, którego baza nie zapisała** |
| P1.7 | Przywrócenie kandydata z odrzucenia **nie anuluje zaplanowanego maila odrzucającego** | Kandydat wraca do procesu i dostaje odmowę |

### Produkcyjny obraz anomalii (zmierzony przez PR-00)
176 634 wpisów etapów, 79 581 par kandydat–zlecenie, 53 818 otwartych.
- **79 488** etapów spoza szablonu zlecenia (systemowe — skutek importu z Traffita)
- **499** zatrudnionych bez kontraktu
- **4 544** zduplikowanych „najnowszych" wpisów
- **48** par z wieloma żywymi kontraktami
- 34 040 aktywnych na zamkniętych zleceniach, 19 750 „CV wysłane" bez zapisanego dokumentu

### Co zrobiono — Fala 0 zamknięta w całości
| PR | Co dowiózł |
|---|---|
| **PR-00 [#780]** | Raport anomalii — liczby powyżej. Nic nie naprawia, ale wiemy, skąd startujemy |
| **PR-01 [#782]** | Uprawnienia: viewer wypada, sourcer traci dostęp do etapów końcowych i stawek |
| **PR-02 [#784]** | Normalizacja stawek 168 h/mies. i 21 dni/mies., blokada obchodzenia zatwierdzeń, twarde usuwanie → 409, przywrócenie anuluje maila odrzucającego |
| **PR-03 [#786]** | Karta wraca na miejsce po błędzie, akcje używają nowego identyfikatora, potwierdzenie przy „Zatrudniony" |
| **PR-04 [#788]** | Czyszczenie HTML, linki do CV z terminem ważności i limitem otwarć, lista aktywnych linków z możliwością odwołania |
| **PR-05 [#790] + PR-05b [#792]** | Każdy etap dostaje stabilne znaczenie niezależne od nazwy kolumny. **Na produkcji: 3 procesy w 100% zmapowane** |
| **PR-06 [#809]** | Powstaje brakujący obiekt „kandydat w zleceniu" — **na razie tylko równolegle, do porównania**. Stary silnik nadal rządzi |

### Co zostało
- **PR-07** (następny) — nienaruszalna księga zmian i jedna komenda na każdą zmianę stanu. **To moment przełomowy** — dopiero od niego system ma jeden proces.
- **PR-08–11** — przełączenie tablicy na nowy silnik, bezpieczna wysyłka powiadomień, operacje zbiorcze v2.
- **PR-12–15** (Fala 2) — przeliczanie stawek i walut, wersjonowane dokumenty, **rekord zgłoszenia do klienta i prawdziwe „Wyślij klientowi"**. Autor planu wskazuje PR-15 jako **największą wartość biznesową** po containmencie.
- **PR-16–18** — jednolite oceny, rozmowa jako obiekt, obowiązki feedbacku.
- **PR-19–21** — wersjonowana oferta, prawdziwe obsadzenie zamiast dwuznacznego „zatrudniony", nowa tablica i raporty.

### Świeży audyt z 17.07
- **N2 [P1] — potwierdzone w kodzie 20.07:** zabezpieczenie „backfill już trwa" jest ustawiane o ułamek sekundy za późno. **Dwa szybkie kliknięcia = dwa równoległe przenoszenia danych.** Poprawka to jedna linia. Warto zrobić **przed** uruchomieniem przenoszenia na pełnej bazie.
- **N3 [P1]** — po „Usuń z rekrutacji" nowy rekord procesu zostaje jako pusty duch. Dziś nieszkodliwe, ale **przy PR-07/08 duchy wrócą na tablicę jako zombie**. Musi wejść w zakres PR-07.
- **N4 [P2]** — rozjazd numeracji migracji, brak wpisu scalającego (patrz sekcja 15).
- **N5 [P3]** — w domyślnym szablonie „Zatrudniony" stoi przed „Onboarding". Przy PR-07 lejek trzeba liczyć po znaczeniu etapu, nie po kolejności kolumn.

### Krok operacyjny, który nie został wykonany
**Przenoszenie ~79,5 tys. par do nowego modelu (PR-06) prawdopodobnie nigdy nie ruszyło na produkcji.** Miało być odpalone zaraz po odzyskaniu Coolify. Bez niego PR-07 nie ma na czym stanąć.

---

## 6. Moduł 5 — Kontrakty, onboarding, rozliczenia, offboarding

**Plan:** 41 PR-ów · **Zrobione:** 6 · **Odrzucone decyzją:** 3+ · **Zostało:** 31

### Za co odpowiada
Wszystko, co dzieje się **po tym, jak kandydat powie „tak"**: umowa, zamówienie od klienta (PO), stawki, wdrożenie u klienta, sprzęt, rozliczanie czasu, faktury, przedłużenia, zakończenie współpracy.
**Skala: 481 kontraktów, 433 aktywnych, 2,18 mln zł deklarowanej marży miesięcznej.**

### Co audyt znalazł — ryzyka AKTYWNE dziś

| ID | Co jest zepsute | Co to znaczy |
|---|---|---|
| **P0.1** | Kontrakt może być „aktywny" bez podpisanej umowy, bez zamówienia i bez onboardingu. **Sześć różnych ścieżek** potrafi ustawić „aktywny" | Raporty liczą przychód ze współpracy, która prawnie może nie istnieć. Dowód: kontrakt #15 — aktywny, 18 000 zł/mies., a w zakładkach zero dokumentów, zero podpisów, pusta historia |
| **P0.5** | Aktywny kontrakt ma przycisk „Usuń", który kasuje go z bazy razem z dokumentami, aneksami, sprzętem i fakturami | **Jedno kliknięcie = bezpowrotna utrata dowodów prawnych i finansowych.** Nadal otwarte |
| **P0.10** | Treść umowy trzymana jako surowy HTML i pokazywana bez filtrowania; generator PDF może pobierać pliki z sieci i dysku serwera | Osoba edytująca szablon może wstrzyknąć kod przejmujący sesję innego pracownika albo zmusić serwer do pobrania pliku z sieci wewnętrznej. **Nadal otwarte** |
| **P1.1** | **Nie istnieje jeden rekord „współpracy"** łączący ofertę → placement → umowę → zamówienie → stawki → onboarding → rozliczenia | To przyczyna źródłowa wszystkich rozjazdów. Profil klienta Bank Pekao pokazuje jednocześnie: 1 aktywnego konsultanta, „Placementy (0)" i LTV 0 zł |
| **P1.7** | Zakończenie współpracy nadpisuje *planowaną* datę końca datą *faktyczną* | Nie da się policzyć, ilu odeszło przed czasem. Wszystkie 29 zakończeń ma powód „nieokreślony", a **raport pokazuje 100% retencji dla wszystkich klientów** — liczba nieprawdziwa i niebezpieczna w rozmowie z klientem |
| **P1.3/P1.5** | Data końca zamówienia w dwóch miejscach; stawka w ośmiu reprezentacjach | Alert czyta inne dane niż ekran. Na produkcji widoczna marża **−1,00 zł** |
| **P1.8–P1.10** | Onboarding to dowolna lista „do zrobienia"; **offboarding nie istnieje w ogóle**; sprzęt można oznaczyć jako zwrócony bez daty | Przy zakończeniu nikt nie wymusza odebrania dostępów ani zwrotu laptopa |
| **P1.13** | Generator umów B2B tworzy nową wersję roboczą przy każdej akcji | Na produkcji: **19 wersji roboczych „do uzupełnienia"** — nie wiadomo, która jest prawna |

### Produkcyjny obraz anomalii (zmierzony przez PR-00)
- **433** aktywnych kontraktów bez powiązanego zlecenia (**100%!**)
- **415** aktywnych bez dokumentu (96%)
- **395** bez pokrycia zamówieniem (91%)
- 49 bez stawek, 29/29 zakończeń bez powodu, 10 aktywnych przed datą startu

**Wniosek autora:** anomalie to NORMA, nie brzegi. Twarda bramka „nie startuj bez kompletu" zablokowałaby cały biznes — potrzebny masowy backfill z odstępstwami dla danych historycznych.

### Ryzyka „na przyszłość" — podpis elektroniczny jest WYŁĄCZONY
`SIGNING_ENABLED=False`, `AUTENTI_ENABLED=False`. Zweryfikowane. Więc poniższe to ryzyka przed uruchomieniem, nie aktywne dziury: link do podpisu nieunieważniany przy wycofaniu; brak walidatora = system **przyjmuje** dokument jako podpisany zamiast odmówić; podpis nie zawsze dotyczy niezmiennej wersji dokumentu.

### Co zrobiono
| PR | Co dowiózł |
|---|---|
| **PR-00 [#789]** | Raport 16 nieprawidłowości cyklu życia kontraktu — liczby powyżej |
| **PR-01 [#791]** | **Zamyka najgroźniejszą dziurę:** każdy zalogowany (także viewer) mógł wejść w generator B2B z cudzym numerem kontraktu i **nadpisać datę startu, stawkę i cały harmonogram stawek** |
| **PR-01b [#793]** | Koniec pobierania cudzych aneksów MSA przez zgadywanie numerów |
| **PR-01c [#806]** | Faktury tylko dla ról z uprawnieniem finansowym |
| **PR-01d [#810]** | Stawki i marże zaciemnione dla ról bez uprawnień finansowych, także w eksportach |
| **PR-02 [#794]** | Zakończenie z datą przyszłą przestało kończyć umowę **dziś** — konsultant nie znika z aktywnych, mimo że dalej pracuje |

### Co zostało — najpilniejsze
- **PR-03a — zakaz twardego usuwania.** Aktywnej umowy, faktury ani dokumentu nie da się skasować; zamiast tego unieważnienie z powodem.
- **PR-03b — bezpieczne generowanie HTML/PDF.** Filtrowanie treści, izolowana ramka, generator bez dostępu do sieci i dysku. **Wymaga świeżej sesji** — to bezpieczeństwo renderowania, wymaga ostrożnego czytania.

To **jedyne dwie aktywne, niezałatane dziury bezpieczeństwa** w tym module.

Dalej: Fala B (niezmienne wersje dokumentów, 5 PR), **Fala C — jeden rekord współpracy zamiast dziesięciu prawd, największa wartość biznesowa** (5 PR), Fala D (zamówienia i jeden rejestr stawek, 5 PR), Fala E (onboarding, sprzęt, **prawdziwy offboarding**, naprawa raportu retencji, 5 PR), Fala F (czas pracy — odchudzona), Fala G (odporność i spójne raporty, 7 PR), Fala H (naprawa danych i przełączenie, 2 PR).

### Decyzje właściciela już podjęte
1. **Autenti OUT** — pomijamy PR-y specyficzne dla tego dostawcy e-podpisu.
2. **Faktury zostają ręczne** — Fala F odchudzona o automatyzację (PR-29/30/31).
3. **„Fail-closed przy starcie" ODRZUCONE** — dokładnie ten mechanizm spowodował wcześniejszą 30-minutową awarię.

> **Warto rozważyć osobno:** decyzja o ręcznych fakturach słusznie usuwa automatyzację, ale PR-29 zawierał też zwykłą higienę ręcznego rejestru: kwota faktury jest dziś **liczbą całkowitą** (grozi błędami w groszach), fakturę można skasować i dowolnie zmienić jej status. To nie wymaga żadnej automatyzacji.

---

## 7. Moduł 6 — Komunikacja, kalendarz, zadania, automatyzacje

**Plan:** 73+ PR-ów · **Zrobione:** cała Fala A (9 ustaleń) · **Reszta odrzucona decyzją**

### Za co odpowiada
Cała warstwa kontaktu: maile do kandydatów, czat zespołu, notatki, powiadomienia, kalendarz, telefony z transkryptami, oraz **24 automaty działające w tle**.

### Co audyt znalazł — 17 problemów krytycznych

| ID | Co było zepsute | Co to znaczyło |
|---|---|---|
| **P0.1** | Główny przycisk „Email" wywoływał endpoint, który w kodzie ma napisane wprost **„SYMULACJA"** — nie wysyłał nic, ale zwracał sukces i zapisywał do historii „email_sent" | **System pokazywał „Email wysłany", a żaden e-mail nigdy nie wychodził.** Rekruter był przekonany, że kandydat dostał wiadomość |
| **P0.2** | Podgląd maila podstawiał na sztywno „Senior Java Developer", datę z 2025 i widełki płacowe — niezależnie od wybranej rekrutacji | Rekruter mógł wysłać kandydatowi **nieprawdziwe warunki zatrudnienia** |
| **P0.4** | Licznik nieprzeczytanych miał błąd logiczny sprowadzający zapytanie do „nie wybieraj niczego" | **Dzwoneczek zawsze pokazywał zero.** „Oznacz wszystkie" nie zmieniał ani jednego rekordu |
| **P0.5** | Szablony maili pozwalały każdemu wpisać `{{ candidate.email }}` i renderować kolejne numery ID | **Wyciek danych osobowych całej bazy** przez zwykłą pętlę po numerach |
| **P0.7** | Kalendarz zwracał wszystkie wydarzenia wszystkim, z opisami, e-mailami uczestników i linkami do nagrań | **Każdy pracownik widział kalendarz każdego innego** i mógł skasować cudze spotkanie |
| **P0.8** | Import kalendarza przyjmował dowolny adres i podążał za przekierowaniami | Pracownik mógł zmusić serwer do odpytania wewnętrznej usługi firmy albo adresu metadanych chmury (**tam bywają klucze dostępowe**) |
| **P0.9** | Wysyłka przez Microsoft 365 sprawdzała tylko „czy zalogowany" | **Konto tylko-do-odczytu mogło wysyłać prawdziwe maile w imieniu firmy** |
| **P0.10** | Admin i Delivery Lead mieli domyślny dostęp do pełnej treści cudzych skrzynek | Czytanie cudzej korespondencji bez terminu, powodu i śladu |
| **P0.13** | CloudTalk dopasowywał rozmowę do kandydata **po ostatnich 9 cyfrach telefonu**, przy kolizji brał pierwszego z brzegu | **Prywatny transkrypt mógł trafić do teczki niewłaściwej osoby** — i uruchomić na niej wzbogacanie profilu |
| **P0.15** | Webhook Microsoft odpowiadał „przyjęte" zanim cokolwiek zapisał trwale | Restart kasował zdarzenia bezpowrotnie. Microsoft uznał, że dostarczył — my nic nie mamy |
| **P0.17** | Oznaczenie maila jako prywatnego nie kasowało zapisanych załączników | **CV kandydata zostawało na dysku po tym, jak dane miały zostać usunięte** |

**Największy brak produktowy (P1.1):** w systemie **nie istnieje pojęcie zadania ani follow-upu**. Nie da się odpowiedzieć na pytanie „co mam dzisiaj do zrobienia" ani „kto miał się odezwać do tego kandydata".

Plus: jedna wzmianka `@` generowała dwa powiadomienia i dwa maile; dopisanie `@Ktoś` przy edycji nie powiadamiało nikogo; Slack nie sprawdzał odpowiedzi HTTP (błąd 500 zapisywany jako „wysłano"); przypomnienia **ignorowały ustawiony przez użytkownika czas** i pamiętały wysłane tylko w RAM (wdrożenie w złym momencie = przypomnienie nie dochodzi nigdy); sprawdzanie dostępności mapowało „błąd" na **„wolne"**; panel admina pokazywał „17 z 24 zadań działa", nie odróżniając „wyłączone celowo" od „padło".

### Decyzja właściciela: TYLKO Fala A
Pełny 73-PR-owy „kernel" (trwałe kolejki zdarzeń, dzierżawy dla wielu replik, brokery czasu rzeczywistego) **odrzucony**, bo produkcja ma **jedną replikę serwera** — cała ta maszyneria rozwiązuje problem, którego w tej konfiguracji nie ma.

### Co zrobiono — cała Fala A
| PR | Co dowiózł |
|---|---|
| **PR-01 [#796]** | Koniec fałszywego „wysłano" — stary endpoint zwraca 410, znika sztywny podgląd, UI przechodzi na wysyłkę z własnego klienta pocztowego |
| **PR-02 [#795]** | Prawdziwy licznik nieprzeczytanych i działające „oznacz wszystkie" |
| **PR-03a [#805]** | Podgląd „kto ogląda" za uprawnieniem, e-maile usunięte z danych |
| **PR-04a [#797]** | Renderowanie szablonu wymaga uprawnienia do danych osobowych |
| **PR-04b [#798]** | Notatki wymagają wskazania podmiotu, stronicowanie, redakcja e-maila autora |
| **PR-05 [#805]** | Compose/reply/wysyłka masowa i rozmowy telefoniczne za uprawnieniem operacyjnym |
| **PR-07 [#805]** | Bezpieczny import iCal: tylko HTTPS, każdy przeskok sprawdzany pod kątem adresów wewnętrznych, limit 5 MB |
| **PR-09 [#805]** | Wymuszone szyfrowanie SMTP z weryfikacją certyfikatu |

Automatyczny recenzent złapał przy tym 2 realne błędy (kodowanie `@` w adresie mailto, brak limitu czasu na zapytanie DNS) — oba naprawione.

### Świadomie przycięte lub odłożone
- **PR-00** (inwentaryzacja) — uznana za zbędny narzut.
- **PR-06** (CloudTalk) — integracja uśpiona na produkcji, ryzyko nieaktywne.
- **PR-08** (czyszczenie artefaktów po usunięciu danych) — **wymaga decyzji o retencji, to aspekt RODO**.
- **P0.3** (token logowania ważny 8 h przekazywany w adresie URL WebSocketa, trafia do logów) — **odłożone jako osobny ostrożny PR**. To jedyny większy P0 tego modułu, który został otwarty świadomie.
- **P0.7** (kalendarz) i **P0.10** (skrzynki) — **zablokowane decyzją**: wymagają rozstrzygnięcia, kto co ma widzieć.

### Niezależny audyt z 17.07 — złapał regresję, którą sami wprowadziliśmy
Szczegóły w sekcji 14. Poza tym dwa wzorce systemowe:
- **Rola główna zamiast wszystkich ról** — 4 wystąpienia w 4 plikach. Osoby, które kwalifikującą rolę mają jako drugorzędną, **po prostu nigdy nie dostają powiadomień** (kontraktowych, compliance, sprzętowych, SLA). Cisza jest nieodróżnialna od „brak alertów".
- **Nieograniczone pobieranie całych tabel w pętli** — tabela historii etapów ładowana **w całości do pamięci 2–6 razy co 5 minut**. Rośnie liniowo z historią firmy. Cichy zabójca wydajności, który pogorszy się sam z siebie.

---

## 8. Moduł 7 — Analityka, KPI, raporty, DynaReporter

**Plan:** 43 PR-y · **Zrobione:** 3 · **Zlecone ale niewykonane:** 1 · **Odrzucone:** 1 · **Przeniesione do M5:** 4 · **Zostało:** 34

### Za co odpowiada
Wszystkie liczby o firmie: zatrudnienia, KPI pracowników, lejek, przychód, marża. **DynaReporter** to stary system raportowy, z którego NEXUS ma przejąć analitykę — formalnie „archiwum tylko do odczytu", ale w praktyce część jego ekranów nadal pozwalała wpisywać dane.

**Kontekst:** ten audyt to *przegląd po wdrożeniu*. Wcześniejszy program analityczny (PR 0–8) wdrożono w całości tego samego dnia, a Codex zaudytował świeżo napisany kod.

### Co audyt znalazł

| ID | Co było zepsute | Co to znaczyło |
|---|---|---|
| **P0.2** | Każdy zalogowany mógł wpisać `/dynareporter/rekrutacja` i pobrać dane | **Imienne wyniki pracowników, rankingi i przyznane nagrody dostępne dla dowolnej osoby z kontem** |
| **P0.4** | Raport finansowy przyjmuje okres (np. styczeń 2025), ale zwraca **stan na dziś** — z etykietą „styczeń 2025" | Raport historyczny kłamie. Każda decyzja oparta na historii finansowej jest oparta na złych danych |
| **P0.5** | Stawki z aneksów obowiązujące od konkretnej daty są wczytywane, ale **ignorowane** | Historia przeliczana dzisiejszymi stawkami, a **przyszły aneks zmienia raport z przeszłości** |
| **P0.6** | Cutover sklejał metryki, które nie są tym samym: stary „przychód rozpoznany" → nowy „MRR", „marża operacyjna" → „marża bezpośrednia" | Wykres trendu wygląda na ciągły, ale **w połowie zmienia definicję**. Zarząd widzi trend, który jest fikcją |
| **P0.8** | Weryfikacja **oczekująca lub odrzucona** liczona jako sukces | Odrzucona próba podnosi KPI. **Konkursy i premie mogą nagradzać niewłaściwe zachowanie** |
| **P0.9** | Awaria API zamieniana na zero lub pustą listę: „Brak alertów — wszystko w normie", pięć zer na dashboardzie, a nawet **wymyślone nagrody 5000/3000/2000 jako fallback** | **Najgroźniejszy rodzaj błędu: awaria wygląda dokładnie jak dobry wynik** |
| **P0.10** | Tryb shadow nie wykonywał żadnego porównania i nie zapisywał dowodu | „7 dni testów" mogło minąć **bez ani jednego porównania** |
| **P0.11** | Stary moduł Contract Analytics **sumuje kwoty w różnych walutach bez przeliczania**, a konwersja ma awaryjny kurs 1:1 | EUR dodawane do PLN nominalnie. Przychód i marża po prostu błędne |

Plus: **dwie różne definicje „komu zaliczamy zatrudnienie"** (dashboard przypisuje osobie, która przesunęła kandydata; KPI i konkursy — pierwszemu weryfikatorowi), więc ta sama osoba ma inne wyniki na różnych ekranach, a konkurs może wyłonić innego zwycięzcę niż dashboard. „Zespół" faktycznie oznacza „cała organizacja". Dashboard pokazuje jednocześnie „11 zatrudnień w tym miesiącu" i „brak ostatnich zatrudnień". Selektor okresu na `/insights` jest **dekoracyjny** dla części widgetów. Widget „Przetargi" bierze wartość przetargu **z widełek wynagrodzenia kandydata**.

### Co zrobiono
| PR | Co dowiózł |
|---|---|
| **PR-01 [#799]** | Uprawnienia do pominiętych ekranów — viewer nie zobaczy imiennych KPI, szef rekrutacji nie zobaczy finansów |
| **PR-02 [#804]** | Prawdziwy tryb tylko-do-odczytu — blokada zapisu po stronie serwera (nie tylko chowanie przycisków). Koniec „dwóch prawd" |
| **PR-05 [#807]** | Zamrożenie cutovera bez dowodu zgodności; endpoint debugowy przestał kasować historię i pokazywać ślady błędów |

### Co zostało — z jednym ważnym wyjątkiem
**PR-03 [ZLECONE ALE NIEWYKONANE]** — usunięcie zamiany błędu na zero i zmyślonych nagród w **12 miejscach**. Został zlecony osobnej sesji i **kod nigdy nie wylądował**. To znaczy, że **P0.9 nadal jest otwarte: gdy API padnie, użytkownik zobaczy „wszystko w normie" i pięć zer.** Najtańsza do zamknięcia otwarta pozycja o realnym wpływie na zaufanie do liczb.

**PR-04 [ODRZUCONE]** — twarde zatrzymanie startu przy nieudanej migracji. Odrzucone słusznie (to była przyczyna wcześniejszej awarii), ale **ryzyko zostaje**: aplikacja nadal może wystartować „zdrowa" bez kompletnego schematu bazy.

Reszta: Fala B (katalog metryk, zegar analityczny, gotowość danych, cache — 4 PR), Fala C (jedna wersja faktów, zespoły, cele KPI — 8 PR), Fala D (finanse — 4 zostają, 4 przeniesione do M5), Fala E (jeden dashboard zamiast trzech warstw — 8 PR), Fala F (niezawodne procesy w tle — 4 PR), Fala G (dowód zgodności i wygaszenie DynaReportera — 5 PR).

**Blokada dalszych fal nie jest techniczna, tylko decyzyjna** — patrz sekcja 16.

---

## 9. Moduł Klient i zapotrzebowanie

**Plan:** 7 PR-ów · **Zrobione:** 1 · **Zostało:** 6

### Za co odpowiada
Wszystko **zanim zaczniemy szukać kandydata**: kartoteka klienta, kontakty, zespół obsługujący, wiedza o kliencie, umowy ramowe, przyjęcie zapotrzebowania i zamiana go w stanowisko rekrutacyjne.

### Co audyt znalazł
- **M1-SEC-01** — kontakty i wiedzę o kliencie mógł zmienić **każdy zalogowany**. Można było przepisać na siebie relację z kluczowym klientem albo podmienić kontekst, którym karmi się AI. Prywatne notatki relacyjne zawierają urodziny, hobby i dane rodziny — **dane wrażliwe pod RODO**.
- **M1-ID-01** — na produkcji 157 firm, w tym **Bank Millennium ×2, LOTTE Wedel ×2, Visa ×2** oraz techniczny rekord `__traffit_orphans`. Ta sama firma liczona dwa razy w raportach, przychód rozdzielony na dwa rekordy.
- **M1-DATA-01** — baza nie sprawdza, czy zamówienie, kontrakt i stanowisko dotyczą tej samej firmy. **Możliwe zamówienie dla firmy A rozliczające kontrakt firmy B.**
- **M1-DOM-02** — lista stanowisk miała **4036 pozycji**. Pierwszych 20 to szkice, 20 z 20 **bez właściciela i bez TAC**. Jeden szkic miał już **czterech kandydatów w procesie**.
- **M1-FIN-01** — LTV liczone z ograniczonej listy (zależnej od stronicowania), waluty mieszane, czas trwania jako „dni ÷ 30", kwoty rzutowane na liczby całkowite. Profil aktywnego klienta pokazywał dodatnią marżę i **LTV = 0**.
- **M1-FILE-01** — typ pliku weryfikowany po rozszerzeniu, limit rozmiaru sprawdzany **po** zapisaniu całości na dysk (a produkcja już raz padła przez pełny dysk), stary plik kasowany przed zatwierdzeniem nowego.

### Co zrobiono
**PR 1/7 — [ZROBIONE, #770]** — powstał `client_access.py` jako **jedyne źródło decyzji** „kto co może u tego konkretnego klienta". Odpowiedzi API rozdzielone na warstwy: bezpieczne podsumowanie / kontakty / dane prawne / dane finansowe. Obie dziury P0 zamknięte.

### Co zostało
- **PR 2 — ZABLOKOWANE.** Kanoniczny klient: normalizacja nazw, scalanie duplikatów, archiwizacja zamiast kasowania. **Wymaga zapytań kontrolnych na produkcyjnej bazie**, żeby migracja nie wywaliła się na danych — a dostępu do niej dziś nie ma (SSH martwy).
- **PR 3–4, 6–7** — zależą od PR 2 i od decyzji biznesowych.
- **PR 5 (bezpieczne wgrywanie plików) — jedyny, który nie czeka na nic.** Może iść od razu.

**PR 2 blokuje 5 z 6 pozostałych PR-ów, a blokada jest organizacyjna, nie techniczna.** To najtańsza rzecz do odblokowania w całym zestawieniu.

---

## 10. Traffit — integracja dwukierunkowa

**Plan:** 11 PR-ów (0–10) · **Zrobione:** 3 · **Bramka wejściowa nadal zamknięta**

### Czego dotyczy
Dziś dane płyną w jedną stronę (raz dziennie NEXUS pobiera zmiany z Traffita). Cel: praca dwukierunkowa — połowa zespołu w NEXUS, połowa w Traffit, zmiana widoczna po drugiej stronie w ≤15 minut.

### Co audyt znalazł
Audyt dotyczył **nieukończonej wcześniejszej próby implementacji, której nie wolno scalać w całości**:
- **Możliwe wyzerowanie pól kandydata** — prototyp traktował „pola nie ma w odpowiedzi" jako „pole jest puste". **Poprawiasz komuś e-mail, a system po cichu kasuje miasto, kraj i źródło pozyskania.** Najgroźniejszy błąd w dokumencie.
- Kolejka „na sucho" mogła zostać wysłana po włączeniu → **lawina zaległych zmian sprzed trzech dni**.
- Echo notatek i etapów → historia kandydata **podwaja się przy każdym cyklu**.
- Automatyczne łączenie kandydatów **po samym e-mailu** → dwie osoby ze wspólnej skrzynki scalone w jedną.
- Sekret webhooka w adresie URL i w logach.

**Twarde ograniczenia API Traffita** (fakty, nie błędy): brak powiadomień o zmianie kandydata, pliku i notatki → trzeba dopytywać co 5 minut; powiadomienie zawiera tylko identyfikator; brak udokumentowanego podpisu webhooka; pola typu Plik i Lokalizacja nieobsługiwane; brak bezpiecznych operacji usuwania.

### Co zrobiono
- **PR 0 [#765 + #808]** — zapisywanie próbek błędów + naprawa przyczyny (rekordy „withdrawn" bez powodu odrzucenia łamały regułę bazy, generując 311 błędów).
- **PR 2 [#767]** — cała infrastruktura trwałości + przełączniki, **wszystkie WYŁĄCZONE**.
- **PR 3a [#768]** — silnik scalania 3-stronnego ze znacznikiem `MISSING` — bezpośrednia naprawa najgroźniejszego błędu.

### Bramka wejściowa nie została przekroczona
Warunek startu całej integracji to `traffit = healthy` nieprzerwanie przez 48 h. **Produkcja nadal pokazuje `degraded`** mimo naprawy #808. Trzeba sprawdzić, czy poprawka faktycznie zadziałała, czy jest druga przyczyna.

### Co zostało
PR 1 (rozpoznanie API — **wymaga środowiska testowego od Traffita, to główny blokado-twórca**), PR 3b, PR 4–10. PR 10 to nie kod, tylko okno operacyjne z listą kontrolną.

---

## 11. Analityka i statystyki (starszy program, PR 0–8) — WYKONANY W CAŁOŚCI

**Plan:** 9 PR-ów · **Zrobione:** 9 · **Ale: nowa analityka nie jest jeszcze włączona dla użytkowników**

Wszystkie 9 PR-ów zmergowano i wdrożono 16.07 w jednej sesji: naprawa procesu wdrożeniowego [#764], containment bezpieczeństwa R0 [#769], fundament danych z okresami w czasie warszawskim [#772], nowe API v1 z 18 końcówkami [#775], poprawne metryki i KPI Coach v2 [#779], nowy frontend [#781], finanse bez przeliczania 1:1 [#783], zamrożenie historii i wygaszanie DynaReportera [#785], bramki jakości w CI [#787].

### Co zostało — same akcje operatorskie do wyklikania przez człowieka
| # | Akcja | Dlaczego pilne |
|---|---|---|
| 1 | **Rotacja klucza InfraReporter** | Klucz usunięto z kodu, **ale nadal żyje w historii gita i nadal działa** po stronie dostawcy. To niezamknięty incydent bezpieczeństwa |
| 2 | Sekrety `E2E_USER_*` | Bez nich nocne testy obejmują tylko strony publiczne |
| 3 | **Włączenie trybu shadow** (`ANALYTICS_V1_MODE=shadow`) | Minimum 7 pełnych dni z codziennym raportem zgodności. **Tego okna nie wolno skrócić** |
| 4 | Dry-run KPI Coach v2 | 7 dni „co bym wysłał" przed włączeniem powiadomień do ludzi |
| 5 | Backfill i cutover | Po shadow |
| 6 | Kursy NBP (`POST /api/fx/refresh`) | Bez tego kontrakty w euro raportują „niedostępne" |
| 7 | Canary | admin 48 h → DL/HoR 48 h → TAC 72 h → wszyscy |
| 8 | Wygaszanie starego systemu | Usunięcie tabel po 90 dniach — **wymaga osobnej zgody właściciela** |

**Kluczowe:** kod jest gotowy, ale flaga `ANALYTICS_V1_MODE` stoi na `off`. Cała ta praca **nie działa jeszcze dla użytkowników.**

---

## 12. Ręczne wyszukiwanie kandydatów

**Plan:** 21 PR-ów · **Zrobione:** 19 (rozłożone na kilka dni) · **Root cause NADAL otwarty**

### Co audyt znalazł
**Dowód z produkcji (oferta „Data Engineer, ZOB-2846"):** domyślne wyszukiwanie zwróciło **0 wyników**, semantyczne 199, stare AI Matching 89. Rekruter nie miał jak stwierdzić, która lista jest prawdziwa.

- **SEARCH-P0-01** — formularz opisuje widełki jako PLN/h, a baza porównywała je z **miesięcznymi** oczekiwaniami kandydata. Zapytanie „90–150 PLN/h" szukało ludzi chcących 90–150 zł **na miesiąc**. **To była bezpośrednia przyczyna zera wyników.**
- **SEARCH-P0-02** — całe pole „Warszawa / Remote" wysyłane jako jedna nazwa miasta.
- **SEARCH-P0-03** — filtr szukał fragmentu tekstu, więc **„Go" trafiał w „Django"**, a ocena punktowa czytała z zupełnie innych pól.
- **SEARCH-P1-02** — wyszukiwanie semantyczne brało globalny top 200 i **dopiero potem** filtrowało; dobry kandydat spoza dwusetki nigdy się nie pokazał.

### Co zrobiono
19 PR-ów, zweryfikowanych w przeglądarce na produkcji: harness pomiarowy [#730], normalizacja stawek i lokalizacji [#731], polityka dopuszczalności [#735] z egzekwowaniem [#737–739], **wodospad wykluczeń** pokazujący ile kandydatów odpadło na którym filtrze [#743/#745], masowe dodawanie [#746/#749/#750], nowy język zapytań V3 [#762], **shortlista** z backendem, promocją do pipeline'u i UI [#754–757], porównanie świadome zapotrzebowania [#757], pasek etapów nad Kanbanem [#758], zabezpieczenie zapisanych wyszukiwań [#760].

Pełny łuk zadziałał na produkcji: 924 wyniki w 172 ms zamiast zera.

### Co zostało — i dlaczego to nadal boli
**Kanoniczne umiejętności + filtrowanie przed pobraniem + reindeks 54 tys. rekordów.** To jest **realny root-cause zerowych wyników**, potwierdzony wodospadem: `54 096 → „Zapytanie tekstowe: 1" → „Umiejętności: 0"`. Wymaga osobnej sesji z wznawialnym workerem.

Plus: pełna unifikacja zapisanych wyszukiwań (ryzyko „burzy alertów"), Recruiter Workspace, migracja czterech powierzchni wyszukiwania.

### Decyzje biznesowe blokujące
1. **Co znaczy pole `Job.salary_min/max` w istniejących ofertach** — budżet na kandydata czy stawka sprzedażowa dla klienta? Bez tej decyzji nie da się włączyć twardego filtra stawki.
2. **Które typy konfliktów są prawnym twardym blokiem, a które tylko ostrzeżeniem** (czarna lista, wykluczeni klienci, zakaz konkurencji).

> **Poprawka faktograficzna:** w notatkach projektu Faza 1 jest przypisana do PR #727. **PR #727 został zamknięty bez scalenia** — ta sama praca weszła jako **#731**.

---

## 13. Audyt całego systemu (15.07) — nigdy nie zrealizowany jako program

**Werdykt audytu:** system działa na produkcji, ale **nie należy go uznawać za bezpieczny ani operacyjnie zdrowy.**

Ten plan nie był realizowany jako spójny program — jego elementy rozeszły się po modułach M2–M7. Poniżej to, co zostało **nietknięte**.

### NAJPOWAŻNIEJSZE: NEXUS-P0-01 — stałe konto administratora, nadal otwarte

Zweryfikowane w kodzie 20.07:
- `backend/scripts/ensure_claude_admin.py` **istnieje**
- `backend/entrypoint.sh:1837` **nadal go wywołuje przy każdym starcie aplikacji**
- `.gitleaks.toml:33` **nadal pomija cały katalog** `backend/scripts/.+\.py`, więc skaner sekretów tego nie wyłapie

Skrypt przy każdym uruchomieniu tworzy lub aktualizuje konto administratora, wymusza rolę admina i **resetuje hasło do wartości zapisanej w kodzie**.

**Co to znaczy:** to jest **trwałe tylne wejście do systemu, odtwarzane po każdym restarcie**. Zmiana hasła przez człowieka jest cofana przy następnym starcie. Audyt oznaczył to jako najwyższy priorytet całego zestawu — i pozycja jest nadal otwarta.

### Pozostałe nietknięte pozycje
- **NEXUS-P0-02** — ścisła walidacja podpisu (usługa wyłączona, więc ryzyko zawieszone).
- Izolacja publicznego formularza aplikacyjnego — nadal scala w istniejącego kandydata.
- Token odświeżania sesji przekazywany w adresie URL (trafia do logów) — złagodzone przejściem na logowanie wyłącznie przez Microsoft SSO [#814].
- Kwarantanna i antywirus przy wgrywaniu plików publicznych.
- Uprawnienia WebSocketa do konkretnego zasobu.
- **Log audytowy nadal generuje część wpisów przez `Math.random()`** i prezentuje je jak prawdziwe zdarzenia.
- Kopia zapasowa wgranych plików poza serwerem, próbne odtworzenie.
- **CI nadal odpala jawnie wypisaną listę plików testowych**, nie cały zestaw (~113 z 239).

### Co pokryły późniejsze programy
Masowa anonimizacja → M2 [#774] · niedziałające Insights → analityka [#772/#775] · fałszywy „email wysłany" → M6 [#796] · middleware „domyślnie przepuść" → [#812] · wycieki RBAC → M7/M5/M4/klient · wdrożenie bez potwierdzenia CI → [#764]

---

## 14. PR #816 — otwarty, niezmergowany, psuje dane użytkownika

**To jest rzecz, o której warto wiedzieć w pierwszej kolejności.**

Niezależny audyt M6 z 17.07 znalazł **regresję, którą wprowadziła nasza własna Fala A**:

PR-07 (bezpieczny import iCal, w batchu #805) zawęził wyszukiwanie wydarzeń o „kto utworzył" — żeby zamknąć nadpisywanie cudzych wydarzeń. Ale w bazie od dawna istnieje reguła unikalności **bez** tego pola. Skutek:

> Gdy drugi użytkownik importuje kalendarz ze współdzielonym identyfikatorem wydarzenia, wyszukiwanie nie trafia → próba wstawienia → błąd zapisu → **wycofanie całej transakcji → znikają wszystkie wydarzenia z tego importu**. Błąd jest połykany do listy błędów, więc użytkownik nic nie widzi.

**Czyli PR-07 zamienił „cichą podmianę jednego cudzego wydarzenia" na „całkowitą utratę całego importu kalendarza".**

**Stan zweryfikowany 20.07:** PR **#816** („iCal UID collision must not destroy the whole import batch") jest **OTWARTY, niezmergowany**. To jedyna pozycja na całej liście, która **niszczy dane użytkownika teraz**.

---

## 15. Ryzyka infrastrukturalne — zweryfikowane 20.07

### Baza produkcyjna jest 26 migracji za kodem

```
/api/health/alembic →
  db_versions:  ["0152_cv_generated_async_status"]
  code_heads:   ["0177_analytics_snapshots_cutovers", "0178_recruitment_processes"]
```

Produkcyjna baza jest ostemplowana na **0152**, kod jest na **0177/0178**.

**Co to znaczy w praktyce:**
- **Nowe tabele** (shortlista, procesy rekrutacyjne, tabele analityczne) są tworzone przez mechanizm awaryjny w skrypcie startowym — dlatego shortlista działa mimo braku migracji.
- **Nowe kolumny w istniejących tabelach NIE są** — mechanizm awaryjny ich nie dodaje. Muszą być ręcznie zmirrorowane w `entrypoint.sh`, inaczej funkcja po cichu nie działa.
- **Zweryfikowane:** migracja `0172_job_shortlist_entries` **nie ma mirrora** w entrypoint.

**Zasada na przyszłość:** każda nowa kolumna, typ wyliczeniowy lub dane inicjalne muszą trafić do `entrypoint.sh`, bo sama migracja na produkcję nie dojdzie.

### Dwie głowy migracji, brak wpisu scalającego
Istnieją równolegle `0177_analytics_snapshots_cutovers` i `0177_workflow_revisions`, bez `0179_merge`. Produkcja używa komendy odpornej na taki rozjazd (`upgrade heads`, liczba mnoga), więc żyje — ale **test odtworzenia kopii zapasowej używa `head` w liczbie pojedynczej i się wywali**. Naprawa: jeden pusty wpis scalający, zero zmian w danych.

### Awaria z piątku — czego się nauczyliśmy
Dysk zapełniony w 98,8% przez śmieci z buildów (doba nieudanych deployów = pętla przebudów). Pułapka recovery: `docker container prune -f` skasował bazę Coolify i kontenery aplikacji. Dane ocalały (nie rusza nazwanych wolumenów), ale bezpieczniej używać `docker image prune -af` + `docker builder prune -af`.

**Nierozwiązane:** brak działającego klucza SSH do serwera. Operacje idą przez API Coolify + panel Hetznera, co pokrywa deploy/restart/env, ale **nie pokrywa operacji na poziomie hosta** (docker, df).

---

## 16. Decyzje, które musisz podjąć

Programy nie stoją dziś na braku czasu programistycznego — stoją na braku rozstrzygnięć. Poniżej pogrupowane, od najbardziej blokujących.

### Blokują najwięcej

| # | Pytanie | Co odblokowuje |
|---|---|---|
| 1 | **Zatwierdzona przez DPO macierz: cele, podstawy prawne i okresy retencji danych kandydatów** | M2 PR 2 → a przez to PR 5 i 6. Plus M6 PR-08 (czyszczenie artefaktów) |
| 2 | **Jak odblokować dostęp do produkcyjnej bazy** (SSH nie działa) | Klient PR 2 → a przez to PR 3, 4, 6, 7 |
| 3 | **Komu zaliczamy zatrudnienie — pierwszemu weryfikatorowi czy osobie, która przesunęła kandydata?** | M7 PR-11, a pośrednio całą Falę C analityki. Dziś są **dwie sprzeczne definicje** działające równolegle |
| 4 | **Skąd bierzemy prawdę o tym, kto jest w czyim zespole?** | M7 PR-13. Dziś „zespół" = cała organizacja |
| 5 | **Czy Delivery Lead widzi finanse tylko swoich klientów, czy w ogóle?** | M7 PR-14, M5 §21.7 |

### Pipeline i kontrakty
6. **Co dokładnie znaczy „zatrudniony", a co „obsadzenie aktywne"?** W którym momencie liczymy sukces w raportach?
7. **Kiedy przywracamy tę samą rekrutację, a kiedy zakładamy nową?** (kandydat odrzucony w marcu aplikuje w lipcu)
8. **Czy zamówienie od klienta jest twardym warunkiem startu dla każdego klienta?** Na produkcji **91% aktywnych kontraktów nie ma pokrycia zamówieniem** — twarda bramka zablokowałaby biznes.
9. **Który system jest źródłem prawdy — NEXUS czy Traffit** — dla każdego pola i stanu?
10. **Ile godzin to dzień, ile dni to miesiąc, i z jakiego źródła kurs walutowy?**

### Komunikacja i dane osobowe
11. **Czy administrator ma prawo czytać cudzą skrzynkę bez formalnej procedury awaryjnej?** (blokuje M6 P0.10)
12. **Jaki zakres widoczności ma rekruter i Delivery Lead?** (blokuje M6 P0.7 — kalendarz)
13. **Jak długo przechowujemy treść e-maili, czaty, transkrypty i nagrania?**
14. **Kto widzi prywatne notatki relacyjne o kontaktach klienta** (urodziny, rodzina, hobby)?

### Wyszukiwanie
15. **Co znaczy pole widełek w istniejących ofertach** — budżet na kandydata czy stawka dla klienta?
16. **Które konflikty są prawnym twardym blokiem, a które ostrzeżeniem?**

### Traffit
17. **Czy Traffit udostępni środowisko testowe i klienta API?** Bez tego stoi cały program.
18. **Czy akceptujesz, że jeśli limity API nie pozwolą przeskanować plików w 10 minut, synchronizacja CV pozostanie wyłączona?**

---

## 17. Co zrobiłbym w tej kolejności

### Natychmiast (godziny)
1. **Zmergować #816** — to jedyna rzecz, która niszczy dane użytkownika teraz.
2. **Zamknąć tylne wejście administratora** (NEXUS-P0-01): usunąć wywołanie z `entrypoint.sh:1837`, zawęzić wyjątek w gitleaks, potem dezaktywować konto i przejrzeć logowania. To najwyższy priorytet całego audytu systemowego, otwarty od 15.07.
3. **Zacommitować 13 dokumentów-planów do repozytorium.** Dziś leżą jako pliki nieśledzone przez gita w nieaktualnym katalogu roboczym. Znikną przy pierwszym porządkowaniu — a to jedyny zapis tej całej pracy koncepcyjnej.
4. **Rotacja klucza InfraReporter** — nadal działa, nadal jest w historii gita.

### W tym tygodniu (dni)
5. **N-01 matching** — marketplace po cichu gubi wszystkie alerty, gdy do oferty pasuje więcej niż jeden kandydat. To wyjaśnia, dlaczego „marketplace nic nie znajduje".
6. **N-04…N-07** — jeden PR czyszczący cache po zmianie stawki, lokalizacji i klienta oferty. Dziś zmieniasz stawkę, a system pokazuje stare oceny.
7. **M7 PR-03** — zlecony, nigdy nie wykonany. 12 miejsc, gdzie awaria API wygląda jak dobry wynik.
8. **M5 PR-03a** — zakaz twardego usuwania aktywnych umów i faktur.
9. **N2 (M4)** — jedna linia, przed uruchomieniem przenoszenia danych.
10. **Migracja scalająca `0179`** — pusty wpis, naprawia test odtworzenia kopii.
11. **Dopisać 9 plików testów matchingu do obowiązkowej bramki CI** — bez tego powyższe fixy nie są chronione.

### Decyzje do rozmowy (nie do kodowania)
12. Punkty 1–5 z sekcji 16. Trzy z nich to rozmowy na pół godziny, a odblokowują kilkanaście PR-ów.

### Dopiero potem
13. **M5 PR-03b** (bezpieczeństwo renderowania HTML/PDF) — wymaga świeżej sesji, to praca wymagająca skupienia.
14. **Uruchomienie przenoszenia danych M4** (~79,5 tys. par) → dopiero potem PR-07.
15. **Włączenie analityki v1** — sekwencja shadow 7 dni → canary → cutover.

---

## Załącznik — mapa PR-ów z 16–17.07

| PR | Program | Co |
|---|---|---|
| #758, #760, #762, #766, #773 | Wyszukiwanie | Pasek etapów, containment zapisanych wyszukiwań, język zapytań V3, kontrast, odświeżanie Kanbana |
| #759 | AI matching | Endpoint audytu produkcji |
| #763, #764, #777 | Infrastruktura | Kolejka Coolify, bramka wdrożeniowa, konfiguracja recenzenta |
| #765, #767, #768, #808 | Traffit | Próbki błędów, trwałość integracji, silnik scalania, naprawa `withdrawn` |
| #769, #772, #775, #779, #781, #783, #785, #787 | Analityka (PR 1–8) | Cały program, wdrożony |
| #770 | Klient | Containment uprawnień |
| #774 | M2 Kandydaci | Containment P0 |
| #776, #778 | M3 Matching | Containment backend + zaufanie do UI |
| #780, #782, #784, #786, #788, #790, #792, #809 | M4 Pipeline | Fala 0 + workflow + rekord procesu |
| #789, #791, #793, #794, #806, #810 | M5 Kontrakty | Inwentaryzacja + RBAC + finanse + daty |
| #795, #796, #797, #798, #805 | M6 Komunikacja | Cała Fala A |
| #799, #804, #807 | M7 Analityka | Uprawnienia + tryb read-only + zamrożenie |
| #811 | Infrastruktura | Alerty dysku (piątek) |
| #800–#803 | M6 | Zamknięte bez scalenia — zwinięte w batch #805 |
| **#816** | **M6** | **OTWARTY — naprawa regresji iCal** |
