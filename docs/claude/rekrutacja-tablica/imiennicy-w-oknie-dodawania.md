# Imiennicy w oknie „Dodaj kandydatów do pipeline” (13.10.2026)

<!-- indeks: telefon, e-mail i miasto w wierszu, szukanie po numerze, „Scal…” -->

Zgłoszenie rekrutera 13.10.2026: w oknie „Dodaj kandydatów do pipeline”
(`AddCandidatesQuickModal`, przycisk na Tablicy) dwie osoby o tym samym
imieniu i nazwisku wyglądały identycznie. Na produkcji 9 527 z 65 783
kandydatów (14,5%) ma imiennika; w 700 grupach dwa rekordy mają ten sam
numer, czyli to zwykle ta sama osoba zapisana dwa razy. Artur zatwierdził
D1–D6 z makiet (https://claude.ai/artifact/UidzDHHjGHMDuutb4zB21L).

- **Wiersz ma trzy linie (D1, D5).** Druga: telefon (pełny, jak w kolumnie
  „Telefon” listy Kandydaci), e-mail, miasto; brak danych jest napisany
  („brak telefonu”, „brak e-maila”). Trzecia, w jednej linii: kategoria,
  „ostatnio MM.RRRR: etap · rekrutacja” albo „jeszcze w żadnej rekrutacji,
  dodany MM.RRRR”, źródło. Data i wynik stoją na początku, bo przy obcięciu
  odpada koniec nazwy rekrutacji. Trzecia linia nie może się zawijać:
  w 1280 × 720 mieszczą się wtedy jeszcze cztery–pięć osób.
- **„Profil” i „Scal…” stoją obok przycisku wiersza, nie w nim.** Wiersz
  jest przyciskiem zaznaczania; link albo przycisk w środku to niepoprawny
  HTML i klik zaznaczałby osobę. „Profil” otwiera nową kartę
  (`/candidates/{id}?from=job&jobId=…`), okno i zaznaczenie zostają.
- **Pasek imienników (D2)** pojawia się tylko, gdy co najmniej dwie osoby
  (wyniki + „Już w tej rekrutacji”) mają to samo imię i nazwisko —
  porównanie bez wielkości liter i nadmiarowych spacji (`nameKey`).
- **Szukanie po numerze i e-mailu (D3)** było już w wyszukiwarce
  (`text_mode=auto`); pole mówi o tym w podpisie, a linia stanu pisze
  „Szukam po numerze telefonu” / „Szukam po adresie e-mail” z
  `meta.interpretation`. Pasujący numer albo adres jest podświetlony.
- **„Już w tej rekrutacji” (D4).** `POST /api/search/candidates` z
  `exclude_in_job_id` dalej pomija osoby z kartą w tej rekrutacji, ale przy
  frazie dosłownej (`text_mode_applied == "literal"`: imię i nazwisko,
  telefon, e-mail) i dostępie do rekrutacji zwraca `in_job_matches` —
  najwyżej 5 osób z tą samą frazą i filtrami, z etykietą karty („Odrzucony
  08.10.2026 (osoba)”, „Screening od 09.10.2026”). Przy frazie „po
  znaczeniu”, kubełkach i bez frazy lista jest pusta: to przeglądanie, nie
  szukanie konkretnej osoby. Karta w toku nie ma akcji. Zamknięta ma
  „Przywróć” — **ruch karty** (`usePipelineMoveCore` + `restoreMovePayload`),
  ten sam co w oknie „Dodaj do rekrutacji”
  (`dodaj-do-rekrutacji-zamknieta-karta.md`); cel ruchu i wersję procesu
  liczy `proposals_bulk.in_job_cards` tak samo jak `closed_card_skip`.
- **Ostatnia rekrutacja (D5)** to ostatni ruch karty w INNEJ rekrutacji
  (`services/candidate_job_cards.latest_cards` z `exclude_job_id`),
  w zakresie `job_read_scope_clause` pytającego — nazwa rekrutacji, której
  ktoś nie widzi, nie wychodzi przez wyszukiwarkę. Liczona tylko przy
  `exclude_in_job_id`, jednym zapytaniem na stronę; główna lista kandydatów
  tego nie płaci. `last_recruitment: null` = brak historii,
  brak pola = serwer nie liczył (wtedy wiersz nic nie mówi).
- **Ten sam numer (D6)** porównujemy po ostatnich 9 cyfrach — tą samą regułą
  co wyszukiwanie po telefonie (`phone_digits_clause`). Pierwszy wiersz
  z numerem jest bez plakietki, kolejne mówią „Ten sam telefon co N. wiersz”;
  numer osoby z „Już w tej rekrutacji” ma pierwszeństwo („…co osoba już
  w tej rekrutacji”). „Scal…” widzi ten, kto może scalać
  (`candidate.write` + admin albo Head of Recruitment, jak w profilu);
  otwiera `CandidateMergeDialog` z wcześniejszym wierszem jako profilem,
  który zostaje. Nic nie scala się samo — numer bywa firmowy.

- **Poprawki po audycie 13.10.2026 (14.10.2026).** Audyt pokazał, że
  „000 000 000” u dwóch różnych osób dawało „Ten sam telefon” i „Scal…”,
  a pole z dwoma numerami porównywało tylko ostatni. Teraz:
  zaślepka (ostatnie 9 cyfr to ta sama cyfra: „000 000 000”, „111 111 111”)
  nie jest numerem; każdy numer z pola liczy się osobno — numery rozdziela
  wszystko poza cyframi, spacją, „+”, „-”, „.” i nawiasami („/”, „,”, „lub”,
  „wew.”). Reguła jest w dwóch miejscach i mówią to samo: `phoneKey` /
  `phoneKeys` w `add-candidates-identity.ts` oraz `_normalize_phone` /
  `_phone_keys` w `dedup_service.py` (`/check-duplicates` w oknie scalania,
  dopasowanie rozmowy CloudTalk — telefon z zaślepki nie trafia w nikogo).
  Podświetlenie szukanego numeru to podciąg cyfr pola (`phoneMatchesQuery`),
  jak `phone_digits_clause`, więc świeci też przy 6–8 cyfrach. W trakcie
  „Przywróć” okna nie da się zamknąć (Escape, tło, „Zamknij”, „Anuluj”) —
  ruch karty może jeszcze pokazać swoje okna, jak w `AddToRecruitmentDialog`.

- **Adres e-mail bez literówek (20.10.2026).** Zgłoszenie: `borysiewicz@onet.pl`
  dawał 476 wyników — gałąź literówek (trygramy, próg 0,2) łapała każdego
  z adresem w `@onet.pl`, a właściwa osoba (już w tej rekrutacji) stała
  w sekcji „Już w tej rekrutacji” pod 25 obcymi wierszami. Fraza w kształcie
  e-maila (`detect_text_mode(...).kind == "email"`) nie ma progu literówek
  (`literal_text_threshold` → `None`): trafia ją tylko podłańcuch w polach,
  CV i notatkach. W okienku i na liście Kandydaci właściciel adresu stoi
  pierwszy, przed osobą z tym adresem w CV albo notatce (jak UAT B35).

Czego nie robimy: numer nie jest maskowany (lista Kandydaci pokazuje go tym
samym osobom, a rekruter porównuje go cyfra po cyfrze), dodanie imiennika
nie pyta „Czy na pewno?”. Harness: `/preview/add-candidates`.
