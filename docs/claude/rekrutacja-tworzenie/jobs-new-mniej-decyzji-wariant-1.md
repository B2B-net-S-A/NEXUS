# `/jobs/new`: mniej decyzji po odczycie maila (wariant 1 „Porządki”, 23.11.2026)

Decyzja Artura z 23.11.2026 po zgłoszeniu Igora („bardzo długo to zajmuje i dużo
zabawy jest z tymi must have”). Makiety z porównaniem „dziś / po” na stagingu:
https://claude.ai/artifact/5CT33qwDPP5vurc1CVY7yV. Pomiar na kopii z 23.11
(116 rekrutacji z 45 dni): mediana od odczytu maila do „Utwórz” 20 min, po
odczycie 8 braków, formularz 8624 px (12 ekranów przy 1280 × 720), 57%
rekrutacji to powtórka nazwy u klienta, Nordea 47 z 47 rekrutacji bez terminu,
80% rekrutacji to 1 osoba.

Artur zluzował przy tym cztery wcześniejsze reguły. Każdą zmieniaj tylko
nową decyzją:

- **Krytyczne z maila wchodzą od razu** (zmienia D2 z 13.10). Propozycja M1
  (`criticalProposal`: lata w mailu albo technologia z tytułu) ustawia
  poziom „krytyczne”, gdy wiersze przyszły z tego odczytu, a DL nie wybrał
  „Brak krytycznych” ani nie oznaczył krytycznych sam
  (`withReadDefaults` w `lib/job-intake-fill.ts`). Nad wierszami stoi
  „Krytyczne: „Java” — wstawione z propozycji AI (…)” z „Brak krytycznych”
  (zdejmuje też poziom wierszy) i „OK” (`IntakeRequirementProposals`).
  Podpowiedź z historii (`suggestedRowKeys`) dalej czeka na klik DL-a.
- **„Najważniejsze zadanie” proponuje AI** (zmienia „AI nie zgaduje” z #3795).
  `JOB_REQUEST_INTAKE` v16 zwraca `key_task` (jedno zdanie) i `key_task: true`
  przy jednym pytaniu (`_one_key_task_question`; bez zadania znacznik znika).
  Formularz trzyma `keyTaskProposed`: do „Zatwierdź zadanie” albo poprawki
  zdania zadanie jest brakiem `key_task`. „Napiszę sam” czyści pole. Bramka
  serwera (`job_key_task_blockers`) bez zmian, API v1 nadal zgłasza `key_task`
  w `missing`.
- **„Utwórz” zatwierdza pytania i kategorię** (zmienia 02.10 i 04.10).
  `missingFor` nie zna już `questions_review`, a kategoria jest brakiem tylko
  bez wyboru (`competenceCategoryId == null`) — podpowiedź serwera wystarcza.
  Brak odpowiedzi, która odpada, dalej blokuje. Przycisków „Zatwierdź”,
  „Zatwierdź wszystkie” i „Potwierdzam: …” nie ma; klik w inną kategorię
  nadal ją potwierdza i zgłasza różnicę (`cc_override`).
- **Termin i liczba osób z historii klienta** (zmienia „Klient nie podał to
  decyzja” z 04.10). `POST /api/job-intake/read` i `/read-file` niosą
  `client_defaults` (`services/job_intake_client_defaults.py`: 50 ostatnich
  rekrutacji klienta spoza Traffita, od 5 rekrutacji i 80% zgodnych).
  Formularz wstawia „Klient nie podał” albo liczbę osób tylko w pusty
  wpis, z chipem „z historii klienta” (`FieldBasis` `client_pattern` —
  nie „z podobnej rekrutacji”, które znaczy szablon). Termin i liczba z maila
  wygrywają. Awaria zapytania = brak podpowiedzi, odczyt działa.

Zostają decyzją DL-a: hiring manager (u Nordei 36 różnych osób w 47
rekrutacjach) i budżet. Dalsze kroki wariantu 1 (wiersz wymagania w jednej
linii, jedna ramka ostrzeżeń, ogłoszenie przy „Utwórz”) i wariant 2
„Powtórka” idą osobnymi PR-ami.
