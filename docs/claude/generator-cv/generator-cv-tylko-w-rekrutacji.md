# Generator CV tylko w rekrutacji (13.10.2026)

Decyzja Artura z 13.10.2026: zespół pracuje już tylko w NEXUSIE i CV
generuje się wyłącznie w ścieżce rekrutacji — bez osobnego modułu, bez CV
„bez procesu” i bez pliku osoby spoza bazy. Dane z produkcji tego dnia: od
przejścia z Traffita (12.10) 40 z 44 ręcznych generacji szło z rekrutacji,
0 bez procesu, 4 z pliku spoza bazy (wcześniej, 5–8.10, ok. 60% szło poza
rekrutacją, bo zespół pracował jeszcze w Traffit).

- **Gdzie się generuje CV:** wyłącznie `CvGeneratorDialog` z osobą ustaloną
  z góry — karta „CV do klienta” w panelu osoby, profil kandydata („Generuj
  CV” przy podglądzie CV i zakładka „Rekrutacje”), dok kanbanu, okno QC CV
  („Wygeneruj CV”, „otwórz generator” przy braku zrzutu zgody RODO).
- **Stary adres `/cv-generator` przekierowuje** (`legacyCvGeneratorHref`
  w `lib/cv-generator.ts`): `?candidate_id&job_id` → `/jobs/{job}?candidate=…`
  (panel osoby), sam `candidate_id` → profil kandydata, reszta → `/jobs`.
  Bramka w `middleware.ts` zostaje (viewer `user` i tak nie miał wstępu).
  Nie ma go w menu, palecie ⌘K ani w `open_screen` Jarvisa.
- **Formularz** (`components/v2/cv-generator/`): krok „Kandydat” tylko pokazuje
  osobę (bez wyszukiwania, „Zmień” i „Osoby nie ma w bazie? Wgraj jej plik”);
  krok „Proces” bez „Inny klient (bez procesu)”. Osoba bez rekrutacji dostaje
  wyjaśnienie zamiast formularza, a lista braków — `NO_RECRUITMENT_MISSING`.
  Awaria listy procesów ma własny komunikat i nie udaje osoby bez rekrutacji.
  Żądanie zawsze niesie `stage_id` i klienta z procesu; notatka z formularza
  zapisuje się w rekrutacji przed generacją.
- **Usunięte z frontu:** strona `CVGeneratorStandaloneV2`, lista „Moje CV”
  (`MyCvList`, `GeneratedCvRow`), okno udostępniania wygenerowanego CV
  (`CvGeneratedShareModal`, i tak schowane flagą `CV_CLIENT_LINKS_UI_ENABLED`),
  krok pliku spoza bazy (`UploadIdentityStep`, `UploadSources`), klient API
  `identifyUpload` / `cvGeneratedShareApi`, e2e `cv-generator-upload-layout`.
  Gotowe CV widać przy etapie (karta „CV do klienta”) i w plikach kandydata
  (`GET /api/cv-generator/generated?candidate_id=`).
- **Backend bez zmian:** `/identify-upload`, `/generate-upload`,
  `/candidates` (szukanie) i `/generate` ze `stage_id: null` dalej istnieją,
  ale żaden ekran ich nie woła. Wycięcie ich to osobna decyzja.
- Harness `/preview/cv-generator`: stany „Proces z Championem”, „Proces bez
  Championa”, „Osoba bez rekrutacji”, „Wynik”, „Rekrutacja — CV do klienta”.
