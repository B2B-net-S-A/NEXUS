# Lista rekrutacji pamięta ostatnie filtry (13.10.2026)

<!-- indeks: goły `/jobs` otwiera ostatni widok osoby, link z parametrami wygrywa i nie nadpisuje pamięci, „Rekrutacje” w menu nie resetuje, wpis per osoba przeżywa wylogowanie, `keepScope`, zapisy adresu niewidoczne dla routera -->

Zgłoszenie Artura 13.10.2026: po wyjściu z listy i powrocie filtry trzeba było
ustawiać od nowa. Filtry żyły wyłącznie w adresie, a menu „Rekrutacje”,
okruszek i kafel pulpitu prowadzą na goły `/jobs`, który lista traktowała jak
czysty start (reguła z audytu rundy 10, R10-N15-12 — odwrócona tą zmianą).

- **Goły `/jobs` = ostatni widok osoby** (`lib/jobs-list-memory.ts`): zakres,
  sortowanie, stan requestu, filtry paska i trzy przełączniki. Tekstu
  z wyszukiwarki i numeru strony w pamięci nie ma — stara fraza następnego dnia
  chowałaby wiersze. Bez wpisu lista startuje jak dotąd, w zakresie domyślnym roli.
- **Link z parametrami wygrywa** (pulpit, powiadomienie, „Wstecz”) i nie
  nadpisuje pamięci, dopóki osoba sama czegoś nie zmieni: jedno kliknięcie
  w kafel „po terminie” nie może zostać jako „ostatnie filtry”. Pilnuje tego
  stan `viewOrigin` w `JobsListV2` (`link` / `restored` / `user`); pamięć pisze
  tylko `user`, a ustawiają go cztery ścieżki działania osoby: zakres
  (`changeScope`), pasek filtrów (`patchFilters`), pigułka stanu i sortowanie.
  Nowa kontrolka filtra musi iść jedną z nich albo sama ustawić `user`.
- **Linkiem jest adres z kluczem, który lista czyta** (`hasJobsListParams`).
  Same martwe klucze sprzed 25.09.2026 (`type`, `status`, …) to nadal goły adres.
- **„Rekrutacje” w menu przy otwartej liście nie resetuje filtrów** — reset
  robi wyłącznie „Wyczyść” (sortowania nie rusza, jak dotąd). Widok z samymi
  wartościami domyślnymi kasuje wpis. Nietknięty widok z linku ustępuje wtedy
  ostatniemu widokowi osoby. Link z parametrami kliknięty na otwartej liście
  pokazuje widok z linku (wcześniej zostawał stary stan).
- **Wpis jest per osoba i przeżywa wylogowanie**: klucz
  `nexus:jobs-list-filters:<id>` w localStorage, poza prefiksami czyszczonymi
  w `lib/session.ts` (wzorzec `new-job-leads-filters.ts`). To ustawienie widoku,
  a wartością są same klucze i identyfikatory filtrów. Zmiana osoby przy
  otwartej liście („podgląd jako”) przełącza na jej widok i nie zapisuje jej
  cudzych filtrów. Nie dopisuj klucza do `clearSessionArtifacts`.
- **`keepScope`** (`encodeJobsListUrl`): nietknięty link z jawnym zakresem
  równym domyślnemu roli (`/jobs?mine=1` u rekrutera — skrót propozycji,
  kafel „Moje rekrutacje”) trzyma zakres w adresie. Bez tego pierwszy zapis
  robił z niego goły adres, a „Wstecz” z rekrutacji otwierałby pamięć zamiast
  „Moich”. Linki, które mają pokazać konkretny zakres, wysyłaj z jawnym
  parametrem — goły `/jobs` znaczy „to, co ostatnio”.
- **Zapisy adresu zostają niewidoczne dla routera Next**
  (`history.replaceState(window.history.state, …)`): każda zmiana
  `useSearchParams` w liście jest wtedy prawdziwą nawigacją i nie ma „echa”
  własnych zapisów do obsłużenia. Zapis widoczny dla routera przerywałby też
  nawigację w toku (klik w wiersz tuż po wpisaniu tekstu w wyszukiwarkę).
  Skutek uboczny, świadomie zostawiony: po kliknięciu „Rekrutacje” na liście
  otwartej z gołego adresu pasek adresu bywa goły do następnej zmiany filtra —
  filtry stoją na ekranie, a „Wstecz” i F5 oddają ten sam widok z pamięci.
- **Link na adres, który router już zna (14.10.2026).** Audyt 13.10 pokazał,
  że link z parametrami równymi adresowi sprzed naszych zapisów (router go
  nadal pamięta) nie zmieniał `useSearchParams`, więc lista zostawała przy
  starym widoku. `JobsListV2` łapie wtedy klik sam (nasłuch `click` na
  `document`): zwykły klik lewym przyciskiem w `<a>` na tę samą ścieżkę,
  z kluczem listy i zapytaniem równym temu, które zna router → widok z linku
  (`viewOrigin = "link"`, pamięć bez zmian). Ctrl/Cmd/Shift/Alt, `target`
  inny niż `_self`, `download`, inna ścieżka i goły `/jobs` idą jak dotąd.
  `router.push` z kodu na taki adres nadal nic nie zmieni — nowe miejsca,
  które prowadzą na listę z parametrami, niech będą linkami.
- **Harness `/preview/jobs-list-v3`** podaje własny klucz (`memoryKey`), bo
  loguje fikcyjne konto o id 1. Testy plików, które klikają filtry listy,
  czyszczą `localStorage` w `beforeEach` — inaczej goły adres następnego testu
  otwiera filtry poprzedniego.
- Testy: `JobsListV2Memory.test.tsx`, `lib/__tests__/jobs-list-memory.test.ts`,
  `e2e/responsive-preview.spec.ts` („ostatnie filtry wracają po wyjściu” —
  jedyne miejsce, które sprawdza to na prawdziwym routerze).
- **Pusty wynik poprzednich filtrów to ładowanie, nie „nic nie pasuje”
  (14.10.2026).** Lista trzyma poprzednią stronę do czasu odpowiedzi
  (`keepPreviousData`). Otwarta z dwoma zapamiętanymi filtrami („Rekruter: X”
  + „Umowa” = 0) po zdjęciu jednego mówiła „Żadna rekrutacja nie pasuje do
  filtrów”, dopóki serwer — restartowany przy wdrożeniu — nie odpowiedział,
  choć X miał 6 otwartych rekrutacji. `JobsListV2`: `isPlaceholderData`
  z pustą listą = `isLoading`. Pilnuje test w `JobsListV2QuickFilters.test.tsx`.
