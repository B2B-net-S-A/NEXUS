# „Usuń z profilu” przy pliku kandydata — raport (13.10.2026)

Zgłoszenie Artura: profil kandydata da się usunąć w całości, a pojedynczego CV
z profilu nie — „albo jest taka opcja, ale nie wiem, jak to zrobić”.

## Odpowiedź na pytanie

Takiej opcji nie było. Menu „⋯” pliku miało „Podgląd”, „Pobierz”, zmianę
rodzaju, „Ustaw jako główne CV” i „Oznacz jako nieaktualne”, a API nie miało
trasy usuwania pliku kandydata.

## Co jest teraz

- Profil → CV i dokumenty → Pliki → „⋯” przy pliku → **„Usuń z profilu”**,
  z oknem potwierdzenia. Widzą i mogą użyć: **admin i Head of Recruitment**.
  Pozostałe role nie widzą pozycji, a serwer odpowiada im 403.
- Plik znika z listy, podglądu, pobierania, źródeł generatora CV, QC i migawki
  CV etapu. **Nic nie jest kasowane** (decyzja z 26.09.2026): wiersz i plik
  w magazynie zostają, zapisane jest kto i kiedy usunął (migracja 0435).
- Główne CV też wolno usunąć. Serwer nie wybiera następcy; profil zostaje bez
  głównego CV, dopóki ktoś nie kliknie „Ustaw jako główne CV” przy innym pliku
  albo nie wgra nowego.
- W historii profilu pojawia się „Usunięto plik z profilu” (bez nazwy pliku).

Reguła i miejsca w kodzie:
`docs/claude/kandydaci-wyszukiwanie/usun-plik-z-profilu-kandydata.md`.

## Co wyszło po drodze

- **Pierwsza wersja blokowała usunięcie głównego CV**, gdy w profilu było inne
  CV („najpierw ustaw inne jako główne”). Przeklikanie harnessu pokazało ślepy
  zaułek: jedynym „innym CV” był plik „…B2B…” dla klienta w zwiniętej grupie.
  Reguła została uproszczona do „główne CV też wolno usunąć”.
- **Kandydat trzyma własny wskaźnik CV** sprzed listy plików (`cv_filename`,
  `cv_storage_key`, `cv_file_content`). `get_current_cv` do niego wraca,
  a `entrypoint.sh` przy każdym wdrożeniu odtwarza z niego dokument.
- **Bloker z przeglądu bezpieczeństwa:** pierwsza wersja odpinała wskaźnik
  pole po polu (ta sama nazwa → nazwa, ten sam klucz → klucz). Import
  z Traffita wgrywał jednak CV dwa razy pod różnymi kluczami. Pomiar na
  produkcji (tylko odczyt, same liczby): 62 216 wskaźników z kluczem, z tego
  55 017 z głównym CV o tej samej nazwie i innym kluczu. U tych osób
  „usunięte” CV dalej szłoby do migawki CV etapu i paczki ZIP. Teraz wskaźnik
  jest odpinany w całości, gdy pokazuje na usuwany plik (klucz, bajty albo
  nazwa), a druga kopia z magazynu dostaje własny usunięty wiersz.
- **Bloker z przeglądu kodu (w tej poprawce):** gdy klucz wskaźnika należał do
  innego pliku z listy, nazwa dalej wskazywała usunięty plik i zasilanie przy
  wdrożeniu odtworzyłoby główne CV pod tą nazwą (89 osób dziś, każda osoba ze
  zgłoszenia z ogłoszenia w przyszłości). Drugi układ: klucz bez nazwy po
  kwarantannie tożsamości (70). Nazwa i klucz są teraz rozstrzygane osobno;
  12 układów wskaźnika sprawdzonych na prawdziwej funkcji.
- **Trzy odczyty nie filtrowały miękko usuniętych plików**: bieżące CV
  (`cv_source`), źródła CV w generatorze i data głównego CV w propozycjach.
  Do tej pory nic nie ustawiało `source_deleted_at` na plikach, więc luka była
  uśpiona; teraz filtr jest w każdym z nich.

## Weryfikacja przed scaleniem

| Co | Wynik |
|---|---|
| `ruff check` / `ruff format --check` na zmienionych plikach | czyste |
| Backend bez bazy: wzorzec bramek tras, sufit sekcji, lustro DDL entrypointu, wybór źródła CV w generatorze, indeks `CLAUDE.md`, stemple | zielone |
| Vitest: `CandidateFilesTab` (19), `capabilities` + inwentarz funkcji profilu (516 łącznie), etykiety osi czasu | zielone |
| `npm run type-check`, ESLint na zmienionych plikach | czyste |
| Harness `/preview/candidate-profile?tab=documents`, 1280×720: menu → okno → plik znika, „Plik usunięty z profilu.” | przeklikane |
| Testy z bazą: `test_candidate_document_removal.py` (role, główne CV, wskaźnik CV, ponowne wgranie, cudzy plik), `test_m365_primary_cv_recovery.py` (poczta nie przywraca) | w CI — patrz PR |
| Wzorzec bramek: nowa trasa przechodzi tylko dla `admin`, `head_of_recruitment` i kont łączonych z HoR | diff w PR |

## Poza zakresem

- `candidate_identity_quarantine._hand_primary_back` przywraca nazwę
  poprzedniego głównego CV bez sprawdzenia, czy ten plik nie został w tym
  czasie usunięty. Wymaga usunięcia poprzedniego głównego CV w trakcie odczytu
  nowego i kwarantanny nowego — wąskie okno, stan sprzed tej zmiany.

- „Przywróć” na ekranie. Ten sam plik można wgrać ponownie; przywrócenie
  starego wiersza to dziś ręczna zmiana w bazie.
- Dane profilu odczytane z usuniętego CV (umiejętności, doświadczenie, tekst
  CV w wyszukiwaniu) zostają. Jeśli usuwane CV należało do innej osoby,
  profil trzeba poprawić osobno.
- Kopie CV w rekrutacjach (oryginał przy etapie, CV firmowe, CV z generatora)
  zostają — to osobne byty.
- Komentarz w `CandidateFilesTab.tsx` („HoR zostaje poza… upload dostałby
  403”) i w teście capability („bez HoR”) jest nieaktualny od 17.09.2026 —
  stan sprzed tej zmiany, nie ruszany.
