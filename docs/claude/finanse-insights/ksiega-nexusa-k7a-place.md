# Księga NEXUSA K7a (14.11.2026): płace liczone w NEXUSIE zamiast w Enovie

Etap K7 planu „Księgowość w NEXUSIE” (https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar),
część pierwsza: dane kadrowo-płacowe, parametry, silnik brutto → netto, lista płac
z zatwierdzeniem drugą osobą, paski, KEDU, PIT-4R/8AR/11, przelewy. Ok. 17 osób:
UoP i zlecenia w zespole oraz zleceniobiorcy u klientów (kontrakty `uzlecenie`).
Migracja `0703_payroll_lists` (`hr_payroll_lists_schema.py`, lustro przez
`hr_schema_bundle`), kod w `backend/app/services/hr/payroll_lists/`, trasy
`/api/hr/payroll-lists`, ekran Księgowość → Płace (`/accounting/payroll`).
Decyzje Artura z 13.11.2026: PESEL i dane do ZUS/PIT szyfrowane, tylko Kadry, Płace
i admin; przełączenie z Enovy po 2–3 miesiącach równoległych zgodnych do grosza.

## Co jest

- **Przełącznik:** moduł `payroll` Księgowości (`ledger/settings.py`, w `BUILT` od
  K7a). Wyłączony = 404 dla każdego poza adminem, także dane osób.
- **Dane osoby** (`payroll_person_data`): jeden zaszyfrowany JSON (`TokenCipher`):
  PESEL albo dokument z datą urodzenia i płcią, imię i nazwisko do ZUS/PIT, adres,
  kod urzędu skarbowego, kod tytułu ubezpieczenia (6 cyfr), PIT-2 (1/12, 1/24, 1/36),
  koszty zwykłe/podwyższone, ulgi (4+, na powrót, dla seniora; dla młodych z daty
  urodzenia, z rezygnacją na wniosek), zlecenie: emerytalne i rentowe / dobrowolne
  chorobowe / wypadkowe, PPK, zwolnienia z FP i FGŚP do daty, rachunek kontraktora.
  Osoba = konto z kartoteką albo kandydat z kontraktem zleceniowym (bez konta).
  Ekrany: Księgowość → Lista płac → „Dane osób” (wszyscy z listy) oraz karta
  „Dane do listy płac” w zakładce Rozliczenia kartoteki (`PayrollDataCard`) —
  wejście dla Administracji współpracy, która bez „Modułu Finanse” nie otwiera
  Księgowości; przy wyłączonym module serwer daje 404 i karty nie ma.
  Student zespołu — z kartoteki (`student_contribution_exempt`,
  `contribution_exempt_until`), kontraktora — z danych płacowych.
- **Parametry** (`payroll_parameter_versions`): pełny zestaw od 1. dnia miesiąca,
  historia z różnicami, „Do potwierdzenia” → „Potwierdzone” (Płace). Zasiew 2026
  do potwierdzenia: składki 9,76/9,76, 1,5/6,5, 2,45, wypadkowa 1,67 (stawka do 9
  ubezpieczonych — sprawdzić zawiadomienie ZUS), FP 2,45, FGŚP 0,10, zdrowotna 9,
  limit 282 600 zł, dobrowolna chorobowa do 23 550 zł, płaca minimalna 4806 zł
  i 31,40 zł/h, skala 12/32% z progiem 120 000 zł, kwota zmniejszająca 3600 zł,
  KUP 250/300 zł i 20%, limit ulg 85 528 zł, ryczałt do 200 zł 12%, PPK 2/1,5.
- **Silnik** (`engine.py`, czyste funkcje) i **lista** (`lists.py`, `sources.py`)
  — reguły niżej. **Paski** PDF (`payslip_pdf.py`), **przelewy** (`transfers.py`).

## Zasady, których łatwo nie zauważyć

- **Miesiąc ZUS i PIT = miesiąc daty wypłaty**, nie miesiąc pracy. Lista 10/2026
  z wypłatą 10.11 to DRA za 11/2026 (ZUS do 15.12) i zaliczki do 20.12 (dzień
  roboczy). Wiek do ulg liczy się na dzień wypłaty: ulga dla młodych obejmuje
  wypłatę do dnia 26. urodzin włącznie.
- **Brutto:** zespół z zamrożonych `payroll_lines` (godziny × stawka + premie,
  tylko PLN; B2B poza listą), zleceniobiorca u klienta z przyjętego rozliczenia
  klienta (`client_settlements.amount_cost`). Kwota wpisana przez Płace
  (`payroll_gross_inputs`, z opisem) wygrywa z obydwoma — UoP z pensją miesięczną,
  L4, niepełny miesiąc, dzieło; kwota 0 zdejmuje pozycję z miesiąca. UoP bez kwoty
  to problem blokujący, nie „miesiąc bez pracy”.
- **Stan narastający roku** (limit 30-krotności, próg skali, limit ulg) = otwarcie
  roku z Enovy (`payroll_year_openings`) + zatwierdzone listy roku z wypłatą nie
  późniejszą. Listy zatwierdza się w kolejności dat wypłaty, także przez granicę
  roku: lista z wypłatą wcześniejszą niż jakakolwiek zatwierdzona nie przelicza
  się i nie zatwierdza (409) — najpierw anulowanie późniejszej. Przelicz,
  zatwierdź, anuluj, kwota Płac i otwarcie roku biegną pod jedną blokadą
  doradczą (`hashtext('hr_payroll_lists')`), bo stan jednej listy zależy od
  innych, a zwykłe odczyty nie widzą niezacommitowanego zatwierdzenia obok
  (przegląd 14.11.2026).
- **Raz w miesiącu wypłaty u płatnika:** kwota zmniejszająca z PIT-2 i koszty
  zryczałtowane UoP. Druga pozycja osoby (np. dwa zlecenia u klientów) albo druga
  lista z wypłatą w tym samym miesiącu bierze tylko resztę (`Title.reduction_used`,
  `kup_used`, stan z innych zatwierdzonych list miesiąca). Kwota zmniejszająca nie
  przekracza podatku pozycji — niewykorzystana część przechodzi na kolejną.
- **Zaokrąglenia:** każda składka osobno do grosza (HALF_UP), podstawa
  opodatkowania i zaliczka do pełnych złotych. FP i FGŚP, wypadkowa i chorobowa
  bez limitu 30-krotności; FP tylko przy podstawie w przeliczeniu na miesiąc co
  najmniej równej płacy minimalnej: kwota Płac może nieść podstawę pełnego
  miesiąca (`fund_basis`, L4, urlop bezpłatny), a UoP zaczęta albo skończona
  w miesiącu przelicza się dniami kalendarzowymi z kartoteki. Zlecenie: zaliczka 12% bez progu (rozlicza
  zeznanie roczne), PIT-2 działa; do 200 zł u nie-pracodawcy — ryczałt 12% od
  przychodu po składkach.
- **Ulgi** mają wspólny roczny limit; w miesiącu przekroczenia składki społeczne
  odliczają się proporcjonalnie do części opodatkowanej, koszty UoP w pełnej
  kwocie. Dzieło bez ulg.
- **PPK pracodawcy** jest przychodem osoby w miesiącu po miesiącu wypłaty
  (przekazanie do instytucji do 15.): lista z wypłatą w miesiącu M dolicza wpłaty
  z list wypłaconych w M−1, minus to, co doliczyły już inne listy z M. Osoba
  z taką wpłatą bez pozycji na liście = ostrzeżenie `ppk_untaxed` z nazwiskiem
  (do ręcznej korekty, kwota w PIT-11).
- **Zatwierdza druga osoba z Płac:** nie ta, która liczyła (CHECK w bazie
  `ck_payroll_lists_second_person`), i bez własnej pozycji na liście. Zatwierdzenie
  zbiera dane jeszcze raz i porównuje `source_hash` — każda zmiana kwot, danych
  osób, parametrów albo innych list po przeliczeniu = 409 „przelicz listę”.
  Problemy blokujące (brak kwoty, brak danych do liczenia, parametry niepotwierdzone
  albo z poprzedniego roku, zlecenie u własnego pracodawcy) = 409 z listą.
  Braki do plików (adres, urząd, kod tytułu) nie blokują listy, tylko KEDU i PIT.
- **Zatwierdzona lista jest nietykalna:** nie przelicza się, nie przyjmuje kwot
  Płac, a jej miesiąc Płac nie otwiera się ponownie (409 `payroll_list_approved`
  w `payroll_close.reopen_month`). Wersja parametrów użyta przez zatwierdzoną
  listę nie zmienia się i nie wycofuje (409) — zmiana od kolejnego miesiąca.
  Anulowanie z powodem, nie przy późniejszej zatwierdzonej liście i nie po
  „Bank wykonał”; następna lista okresu ma numer `LP/RRRR/MM/2`.
- **Swoich danych płacowych, kwoty i otwarcia roku nie zmienia się samemu** (403,
  admin może) — jak własna stawka w Płacach.
- **Kwota Płac dla kontraktu spoza miesiąca** (np. rozliczenie po końcu umowy) też
  jest pozycją listy (`basis.outside_month`) — nie znika po cichu; kontrakt bez
  kandydata = 422 przy wpisie.
- **Kandydat usunięty** (RODO, admin): klucze do `candidates` mają `SET NULL`
  (strażnik `test_every_candidate_fk_has_on_delete_rule`), a dane płacowe,
  pozycje list i otwarcia roku trzymają pseudonim `candidate_ref`
  (`candidate_subject_reference`, jak umowy) — dokumentacja płacowa zostaje.
- **PESEL na zewnątrz tylko jako maska** (kropki i 4 cyfry), bez daty urodzenia,
  gdy wynika z PESEL-u (data i 4 cyfry odsłoniłyby 10 z 11 cyfr). Ten sam PESEL
  u dwóch osób = 409 (skrót HMAC, bez odszyfrowania). Ślad zapisuje nazwy pól.
- **Przelewy:** format i nadawca z paczki przelewów Płac (Elixir-O/CSV, opcja
  domyślnie wyłączona — `batches.ensure_enabled`). Wypłaty na rachunek z danych do
  rozliczeń (zespół) albo z danych płacowych (kontraktor), ZUS na NRS, zaliczki
  i ryczałt na mikrorachunek z tytułem `/TI/N…/OKR/RRMmm/SFP/PIT4R|PIT8AR/TXT/…`
  i klasyfikacją Elixir „71” — do sprawdzenia w banku przy pierwszym imporcie.
  Rachunek zmieniony po pierwszym pobraniu = 409 `batch_account_changed`.
  „Bank wykonał” — Płace, nie osoba z własną pozycją.

## Pliki do wysyłki ręcznej (`kedu.py`, `pit_forms.py`, `forms_pdf.py`, `documents.py`)

- **KEDU miesiąca** (`/declarations/{rok}/{miesiąc}/kedu.xml`) — DRA + RCA za
  miesiąc WYPŁATY ze wszystkich zatwierdzonych list z wypłatą w nim; RCA = osoba ×
  forma (dwa zlecenia u klientów sumują się). Schemat KEDU 5.7 (EWD 2.27 z BIP ZUS,
  ważny od 25.04.2026), wynik przechodzi jego XSD; import do e-Płatnika do
  sprawdzenia na pierwszym miesiącu. Osoba bez identyfikatora, imienia, nazwiska
  albo kodu tytułu blokuje CAŁY plik (409 `kedu_data_missing` z listą osób) — DRA
  bez kogoś z RCA byłaby błędna. Brak REGON-u płatnika = 409. Stopa wypadkowa
  z parametrów ostatniej listy miesiąca.
- **Zgłoszenia** (`/registrations?date_from&date_to`, plik `.xml`) z dat umów,
  nie z listy (7 dni od powstania tytułu): ZUA (UoP, zlecenie z emerytalnym),
  ZZA (zbieg — tylko zdrowotna), ZWUA od dnia po ostatnim dniu tytułu, kod
  przyczyny 100. Student na zleceniu — bez zgłoszenia. Wyrejestrowanie pracownika
  wypada z pliku: tryb i podstawę rozwiązania umowy uzupełnia się w e-Płatniku.
  Oddział NFZ z województwa adresu (albo wpisany kod 01R–16R).
- **PIT-11, PIT-4R, PIT-8AR** (`/years/{rok}/…`) — XML e-Deklaracji (PIT-11 (29),
  PIT-4R (13), PIT-8AR (14) z crd.gov.pl, walidowane XSD) i PDF z tych samych
  pozycji („zestawienie z NEXUSA”, nie formularz urzędowy). Rok = rok wypłaty.
  Ryczałt (do 200 zł) tylko w PIT-8AR. PIT-11 ZIP pomija osoby z brakami (adres,
  urząd, identyfikator; bez PESEL-u — NIP osoby) i wypisuje je w `BRAKI.txt`.
  Otwarcie roku z Enovy wchodzi do PIT-11 jako pozycje syntetyczne (zwolnienie =
  ulga dla młodych); PIT-4R i PIT-8AR obejmują tylko miesiące z listami NEXUSA —
  w roku przełączenia Płace łączą je z Enovą.
- Pobrania mają ślad (`payroll_kedu_downloaded`, `payroll_registrations_downloaded`,
  `payroll_tax_form_downloaded`) bez numerów osób.

## Czego jeszcze nie ma (K7b i dalej)

- Dekret listy płac do księgi (dokument LP z NEXUSA zamiast pliku Enovy z K3c).
- Wynagrodzenie zasadnicze miesięczne UoP, chorobowe z podstawy 12 miesięcy,
  urlop z wynagrodzeniem urlopowym — do tego czasu kwota Płac.
- Ograniczenie składki zdrowotnej do zaliczki wg zasad z 2021 r., koszty 50%
  (prawa autorskie), zbieg zlecenia z UoP u tego samego płatnika — do ręcznego
  policzenia (problem blokujący na liście).
- Wysyłka automatyczna KEDU i e-Deklaracji, powiadomienia o liście do zatwierdzenia.
- **Bloker przełączenia:** porównanie z Enovą do grosza na każdej osobie wymaga
  eksportu list płac z Enovy od Płac (2–3 miesiące równolegle).
