# „Usuń z profilu” przy pliku kandydata (0435, 13.10.2026)
<!-- indeks: kto usuwa plik z profilu (admin, Head of Recruitment), co znika, a co zostaje w magazynie, główne CV i wskaźnik CV na kandydacie, synchronizacja poczty, jak przywrócić -->

Zgłoszenie Artura z 13.10.2026: profil kandydata dało się usunąć w całości,
a pojedynczego CV z profilu już nie — menu „⋯” pliku miało tylko „Oznacz jako
nieaktualne”.

## Reguła (decyzja Artura)

- Zakładka „CV i dokumenty” → Pliki → „⋯” wiersza → **„Usuń z profilu”**.
  Widzą ją i mogą użyć wyłącznie **admin i Head of Recruitment**
  (`CandidateDocumentRemoveAccess` w `api/candidate_access.py`, na froncie
  capability `candidate.document.remove`). Rekruter, Delivery Lead, TCM
  i Finanse dalej wgrywają pliki, zmieniają rodzaj i oznaczają jako
  nieaktualne, ale nie usuwają (403).
- **Nic nie jest kasowane.** Obowiązuje decyzja z 26.09.2026 („nie usuwać nigdy
  żadnych CV”): wiersz `candidate_documents` zostaje, plik w magazynie zostaje.
  Usunięcie ustawia `source_deleted_at` (wyłącznik, który respektują lista
  plików, pobieranie, podgląd, generator, QC i migawka CV etapu) oraz
  `removed_at` / `removed_by` — kto i kiedy. Nie dokładaj tu kasowania obiektu
  z magazynu ani wiersza.
- **Główne CV też wolno usunąć.** Serwer nie wybiera następcy: nowe główne CV
  odświeża profil odczytem AI, a jedynym innym CV bywa plik „…B2B…” dla
  klienta. Profil zostaje bez głównego CV, dopóki ktoś nie kliknie „Ustaw jako
  główne CV” przy innym pliku albo nie wgra nowego. Okno potwierdzenia mówi to
  wprost.
- Dane odczytane wcześniej z usuniętego CV (umiejętności, doświadczenie,
  `raw_cv_text`, wektor) zostają w profilu. Kopie w rekrutacjach (oryginał CV
  przy etapie, CV firmowe, CV z generatora) to osobne byty i też zostają.

## Gdzie to mieszka

- `DELETE /api/candidates/{id}/documents/{doc_id}` (`api/candidates.py`) →
  `services/candidate_document_removal.remove_candidate_document`.
- **Wskaźnik CV na kandydacie.** `candidates.cv_filename`, `cv_storage_key`
  i `cv_file_content` to wskaźnik sprzed listy plików. `get_current_cv` wraca
  do niego, gdy nie znajdzie dokumentu (migawka CV etapu, paczka ZIP),
  a `entrypoint.sh` przy każdym wdrożeniu odtwarza z niego wiersz dokumentu,
  jeśli w profilu nie ma głównego CV ani pliku o tej nazwie. Usunięcie pliku
  odpina więc wskaźnik, gdy pokazuje on na ten plik
  (`_pointer_is_removed_file`): ten sam klucz, te same bajty albo ta sama
  nazwa bez względu na wielkość liter.
- **Ta sama nazwa, inny klucz to ten sam plik.** Import z Traffita wgrywał CV
  dwa razy: raz pod klucz wskaźnika, raz pod klucz dokumentu. Pomiar
  13.10.2026 (tylko odczyt): 62 216 wskaźników z kluczem, 55 017 z nich ma
  główne CV o tej samej nazwie i innym kluczu, 0 kandydatów z bajtami CV
  w wierszu. Porównanie samych kluczy zostawiłoby „usunięte” CV w użyciu u 88%
  osób z bazy. Drugą kopię zapisujemy jako osobny usunięty wiersz
  (`external_source = 'legacy_pointer'`), żeby klucz w magazynie nie stracił
  jedynego wskaźnika.
- **Wskaźnik innego pliku zostaje.** Gdy wskaźnik nazywa starsze CV, które
  dalej leży w profilu (6 748 osób), usunięcie głównego CV go nie rusza;
  odpina go dopiero usunięcie tamtego pliku. Po odpięciu wskaźnik przechodzi
  na główne CV, które zostało, albo jest pusty.
- Bajtów z wiersza kandydata nie zdejmujemy, jeśli tego samego pliku nie ma
  przy dokumencie — wtedy wskaźnik zostaje nietknięty.
- **Odczyty.** Każde zapytanie o pliki kandydata filtruje
  `source_deleted_at IS NULL`. Przy tej zmianie filtr dostały miejsca, które go
  nie miały: `cv_source.current_cv_filters`, źródła CV w generatorze
  (`standalone_service._supported_cv_doc_filter`) i data głównego CV
  w propozycjach (`proposal_facts.main_cv_uploaded_on`). Nowy odczyt
  `candidate_documents` bez tego filtra pokaże usunięte pliki.
- **Poczta M365.** `attachment_handler.try_parse_cv` wskrzesza miękko usunięty
  dokument, gdy TEN SAM załącznik wraca w synchronizacji. Plik z `removed_at`
  u tej samej osoby zostaje usunięty; przypisanie załącznika innej osobie
  (rematch) przywraca go u niej normalnie. Ten sam plik przysłany w nowym
  mailu to nowy załącznik i nowy dokument — jak ponowne wgranie.
- Ślad: wpis `candidate_document_removed` w historii profilu („Usunięto plik
  z profilu”), w `details` tylko id pliku, rodzaj i `was_primary` — bez nazwy
  pliku, bo nazwa CV to zwykle imię i nazwisko.

## Czego to nie robi

- Nie ma „Przywróć” na ekranie. Ten sam plik można wgrać ponownie (powstaje
  nowy wiersz; indeks unikalności po SHA pomija usunięte). Przywrócenie
  starego wiersza to dziś ręczna zmiana w bazie: wyczyścić `source_deleted_at`,
  `removed_at`, `removed_by`.
- Nie czyści danych profilu odczytanych z CV. CV innej osoby w profilu
  rozwiązuje kwarantanna tożsamości, nie usunięcie pliku.
- Nie usuwa CV, które istnieje tylko we wskaźniku pod inną nazwą niż
  jakikolwiek plik z listy. Po usunięciu głównego CV takie CV wraca na listę
  przy najbliższym wdrożeniu (zasilanie w `entrypoint.sh`) i wtedy da się je
  usunąć jak każde inne.
- Usunięcie całego profilu (`DELETE /api/candidates/{id}`, tylko admin) działa
  jak dotąd — patrz `uprawnienia/integralnosc-i-uprawnienia-reguly-po-audytach.md`.

Testy: `backend/tests/test_candidate_document_removal.py`,
`frontend/src/components/v2/files/__tests__/CandidateFilesTab.test.tsx`,
wzorzec bramek `tests/data/authz_golden/candidates.json`.
