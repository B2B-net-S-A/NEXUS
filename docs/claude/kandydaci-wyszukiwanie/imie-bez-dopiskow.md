# Imię i nazwisko bez dopisków (D6, 13.10.2026)
<!-- indeks: dopiski z Traffita, `candidate_name_rules`, 422 przy wpisie, migracje 0436 i 0481 -->

Traffit nie miał pól „zatrudniony”, „czarna lista” ani „szuka aktywnie”, więc
rekruterzy wklejali je w imię: „[ACTIVE] Jan”, „Nowak (zaakceptowany)”,
„(czarna lista) Piotr”. Migracje 0165 i 0232 zdjęły część rodziny; 13.10.2026
w bazie zostało 9 takich dopisków, a jeden wpisano ręcznie w NEXUSIE tego dnia.
Decyzja Artura 13.10.2026: imię i nazwisko to tylko imię i nazwisko, a każda
z tych informacji ma swoje pole.

## Reguła

- **Jedna funkcja:** `app/services/candidate_name_rules.py`
  (`strip_name_markers`, `find_name_markers`, `without_name_markers`). Dopisek
  to segment `[...]`/`(...)`, którego treść NIE jest jednym słowem-nazwiskiem
  z wielkiej litery, albo jest słowem statusu; dalej `zatrudnion*` w dowolnym
  miejscu (0165), słowo statusu przy nawiasie lub ukośniku bez pary i gołe
  słowo statusu na krawędzi pola („ACTIVE Jan”). „Anna (Kowalska)” to drugie
  nazwisko i zostaje (21 takich osób 13.10). Rodzina słów statusu: black list,
  czarna lista, (nie)aktywny, (in)active, passive, zatrudnion*, zaakceptowan*,
  akcept*, eks-/ex-pracownik, były pracownik.
- **Ręczny wpis → 422 przy polu** (`loc: ["body","name"|"lastname"]`, typ
  `candidate_name_marker`, zdanie: „Imię i nazwisko bez dopisków w nawiasie.
  „Szuka aktywnie” ustaw w polu Dyspozycyjność („Aktywnie szuka pracy”),
  czarną listę — w menu profilu („Czarna lista…”); zatrudnienie widać samo
  z umowy.” — od 17.10.2026, gdy pole „Status” zniknęło z okna): `POST /api/candidates` (w handlerze, nie
  w `CandidateCreate`), pola formularza `/from-cv` (przed płatnym odczytem CV),
  `PATCH /api/candidates/{id}` tylko dla pola, które się ZMIENIA — stary
  dopisek nie blokuje edycji telefonu. Front pokazuje zdanie pod polem
  (`lib/name-field-error.ts`, okna „Dodaj kandydata” i „Edytuj dane”).
- **Ścieżki automatyczne zdejmują dopiski przed zapisem**:
  `/api/extension/candidates`, `/bulk-import` (przed walidacją), imię z odczytu CV
  (`/from-cv`, `/cv/preview`, uzupełnianie z CV), import CSV, załączniki M365,
  strona kariery i link zgłoszeń, zgłoszenia, poczta zamówień, scalanie, mapper
  Traffita, import Talent Radar. Testy: `test_candidate_name_marker_paths.py`
  (nowa ścieżka zakładająca kandydata z danych z zewnątrz → dopisz ją tam).
- **Nowa osoba z panelu LinkedIn:** `linkedin_extension_writes.create_candidate`
  czyści pełne `profile.full_name` funkcją `strip_name_markers` **przed**
  podziałem na imię i nazwisko. Polskie znaki i łącznik zostają. Jeżeli po
  oczyszczeniu brakuje imienia lub nazwiska, wraca 422; nie powstaje zastępczy
  profil z samym dopiskiem. Dokładne dopasowanie publicznego linku zwraca
  istniejącą osobę wcześniej — ten zapis nie zmienia jej imienia i nazwiska.
  Regresje HTTP: `test_linkedin_extension_candidate_name_markers.py`.
- **Wartości dłuższej niż 200 znaków reguła nie skanuje**
  (`MAX_SCANNED_NAME_LENGTH`): wzorce są kwadratowe na długim ciągu spacji,
  a import zbiorczy i CSV wołają regułę przed walidacją długości pola (100). Pole, które było samym dopiskiem, zostaje bez zmian (puste imię
  jest gorsze); mapper i korekta 0436 wpisują wtedy „?”.
- **Mapper Traffita używa tej samej funkcji** — import nie przywróci tego, co
  zdjęła korekta. Zdjęty dopisek idzie do `cv_extracted_data.traffit_name_marker`
  (napis z dopiskami po spacji).

## Poprawki po audycie 13.10.2026 (14.10.2026)

- **Import z pliku nie gubi czarnej listy.** Import CSV (`/api/import/candidates`)
  i `/bulk-import` czytają `has_blacklist_marker` na SUROWYM imieniu i nazwisku,
  zanim zdejmą dopisek — „Kowalski (czarna lista)” wchodzi jako „Kowalski”
  ze statusem `blacklisted` (w `/bulk-import` także wbrew `status` z pliku).
  Do 14.10 osoba wchodziła jako aktywna i trafiała do propozycji.
- **Wielowyrazowy nawias z „czarną listą”** („(dodany do czarnej listy przez
  klienta)”) ustawia status — `has_blacklist_marker` sprawdza też zdjęte
  dopiski, nie tylko słowo przy samym nawiasie. Nazwisko „Blacklista” nadal nie.
- **Zaprzeczenie to nie „szuka aktywnie”:** „(nie aktywny)”, „[not active]”,
  „(non-active)” zdejmujemy, ale `has_active_marker` ich nie liczy.
- **„Przywróć z Traffita”** (`restore-from-traffit`) wpisuje migawkę po tej samej
  regule — „[ACTIVE] Jan” wraca jako „Jan”. Migawka będąca samym dopiskiem nie
  daje się przywrócić (`can_restore: false`, 409 `traffit_identity_value_unavailable`).
  Token wersji (`expected_traffit_values`) zostaje surową migawką.
- **Zdanie 422** wskazuje pola okna (AppShell): „Dostępność” jest tam datą.

## Korekta danych 0436

- Migracja `0436_candidate_name_markers` i faza startu
  `repair-candidate-name-markers` w `entrypoint.sh` wołają ten sam kod
  (`app/services/candidate_name_marker_repair.py`): advisory lock, paragon jako
  bramka (`INSERT … ON CONFLICT DO NOTHING RETURNING`), wstępny filtr SQL
  (nadzbiór), decyzja w Pythonie tą samą regułą.
- **Najpierw pole, potem tekst:** czarna lista → `status = 'blacklisted'`
  (chyba że status poprawił człowiek — `_nexus_identity.status_manual`);
  „active”/„aktywny” → `availability_status = 'actively_looking'`, gdy było
  `unknown`, a pole pod ręczną blokadą z takim dopiskiem wraca do wartości
  z Traffita i traci blokadę; reszta — tylko zdjęcie.
- **Bez notatek** (reguła 0399: automaty nie piszą notatek). Prowieniencja
  w `traffit_name_marker`, tylko gdy `cv_extracted_data` jest obiektem.
- Paragon `app_settings['0436_candidate_name_markers']`: liczby i ID (zmienione,
  na czarnej liście, z dostępnością, ze zdjętą blokadą). Stare wartości pod
  `repair_details_0436_candidate_name_markers` (klucz spoza wzorca paragonów —
  nie trafia do publicznego logu). Kolejkę indeksu zapisuje faza startu,
  także po korekcie wykonanej przez migrację (`reindex_recorded`).

## Druga runda 0481 (20.10.2026)

Przeklikanie Opieki pokazało u konsultantów z umową imiona, których 0436 nie
znała (Opieka bierze imię z `candidates.name` + `lastname`). Reguła zna od tego
dnia:

- **klamry** `{...}` jak nawiasy („{ } Jan”);
- **nawias kwadratowy albo klamrę bez pary** („[Jan”, „Jan]”) — para, która
  zostaje, nadal jest nazwiskiem („[Inactivewicz] Jan”). **Okrągły bez pary
  zostaje** — bywa uciętym drugim nazwiskiem albo stanowiskiem i wymaga człowieka;
- **literówkę „acive”** w rodzinie słów statusu („[acive/ Jan”) — tylko zdjęcie,
  bez „szuka aktywnie” (osoba z umową);
- **emoji** (kategoria Unicode `So`, znak łączący ZWJ, selektory wariantu)
  i „?” po emoji zepsutym przy imporcie („?‍? Jan”) na krawędzi pola. Sam „?”
  (zastępnik pustego pola) i łączone znaki diakrytyczne („o” + U+0301) zostają.

Czego reguła **nie** zdejmuje (decyzje Artura 20.10.2026): tytułów po przecinku
(„Kowalski, MBA”, ok. 30 osób) i dwukropka na końcu („Pawe:” to zgadywanie, nie
dopisek). Ręczny wpis z klamrą albo emoji dostaje 422 tym samym zdaniem.

Korekta danych: migracja `0481_candidate_name_markers_v2` i faza startu
`repair-candidate-name-markers-0481` — ten sam rdzeń co 0436, własny paragon
`app_settings['0481_candidate_name_markers_v2']`. Przed regułą biegną trzy
ręczne poprawki rozjechanych pól (`MANUAL_FIXES_0481`, lista „było → będzie”
zatwierdzona przez Artura): klucz to ID, ale zapis zależy od kształtu pól
(`plan_manual_fix`), więc na innej bazie nic się nie dzieje. Na produkcji
20.10.2026 reguła na całym nadzbiorze wstępnego filtra (150 wierszy) zmieniała
dokładnie zatwierdzone osoby.

## Front

- Inicjały liczy `getCandidateInitials` z pierwszej LITERY imienia i nazwiska
  („[ACTIVE] Jan” nie daje „[J”). Tablica liczy inicjały inną funkcją
  (`PipelineCandidateDock`, `workbench-chrome`) — do ujednolicenia osobno.
- Pigułka dostępności zastąpiła „Aktywny/Pasywny” — reguła profilu
  w `ekran-kandydaci-i-profil-kandydata-uproszczenie.md`.
