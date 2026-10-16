# Okienko „Rozmowy” w górnym pasku (13.10.2026)
<!-- indeks: zadania z cyklu (`mine`), czas z agendy, gaszenie osobną trasą, pigułka telefonu -->

Powiadomienia o rozmowach u klienta i prepach (kategoria „Rozmowy”, 9 typów)
stały w dzwonku razem ze wszystkim innym: jeden wiersz na zdarzenie, bez akcji,
część z numerem kandydata zamiast nazwiska. Dzwonek jest czytany w 0–8%,
a telefon po rozmowie u klienta ma okno 30 minut. Decyzje Artura 13.10.2026:
osobna ikona i okienko między „Czatami” a dzwonkiem, dzwonek tej kategorii nie
pokazuje, pigułka pilna tylko dla telefonu po rozmowie, dymki z akcją. Makiety:
https://claude.ai/artifact/Nt9BUPasXNjSYpZGmEpf37, raport
`docs/interview-notifications-window-completion-report.md`.

- **Dwa źródła, jedna czysta funkcja.** Zadania („Teraz”, „Czeka na Ciebie”)
  pochodzą z `GET /api/interview-cycle` — tego samego zapytania co ekran
  „Rozmowy u klienta” i kafel „Dziś”, więc liczby się zgadzają i zadanie znika
  samo po wykonaniu. „Nowe” to nieprzeczytane wiersze kategorii z 7 dni
  (`GET /api/notifications/interviews`). Składa je
  `lib/interview-window.ts` → `buildInterviewWindow`; komponent tylko rysuje.
- **„Moje” wskazuje serwer.** `compute_todos` dopisuje `owner_id`,
  a `load_overview` ustawia `mine` w `todos` i `agenda`
  (`interview_cycle.todo_is_mine`, z zastępstwami). Delivery Lead w zakresie
  „jobs” widzi na ekranie sprawy rekruterów, ale okienko pokazuje tylko
  `mine === true`. Zadanie bez wskazanej osoby nie jest niczyje „moje” —
  adresat zapasowy (nieaktywny właściciel) dostaje powiadomienie w „Nowe”.
  Prep 1 bez terminu jest i Delivery Leada rekrutacji, i właściciela rozmowy,
  bo potwierdzenie terminu mówi rekruterowi „Zaplanuj prep”.
- **Czas liczy przeglądarka z agendy, nie serwer.** Telefon po rozmowie to
  wpis `call` (koniec rozmowy … koniec + okno), zaległy debrief — ten sam wpis
  po oknie; prep i rozmowa wchodzą do „Teraz” kwadrans przed startem.
  Zadanie `call_now` z serwera okienko pomija — inaczej telefon pojawiałby się
  dopiero przy następnym odpytaniu (co 5 min). `debrief_overdue` z serwera
  pomija tylko wtedy, gdy agenda ma wpis `call` tego wydarzenia: agenda sięga
  14 dni wstecz, a zadanie nie ma limitu wieku, więc bez tego starszy zaległy
  debrief gasłby tak, jakby go zapisano.
- **`slots_missing` nie wchodzi do okienka.** To stan do 30 dni, na który
  Delivery Lead nie ma ruchu; licznik na ikonie nigdy by nie gasł. Zostaje na
  ekranie „Rozmowy u klienta”.
- **Sygnał zadania zwija się, informacja ma własny wiersz.** Terminy od
  klienta, wybrany termin, telefon T+15/T+45 i `prep_attention` dają kropkę
  „nowe” przy wierszu pary; potwierdzenie terminu, zapisany debrief
  i eskalacja 2 h zawsze stoją osobno (debrief niesie warunek kandydata).
- **Nieaktualny sygnał chowa stan pary, nie brak zadania.** Tylko gdy
  przegląd jest wczytany, nie `truncated`, zawiera parę i jest świeższy niż
  powiadomienie (`generated_at > created_at`) — lista powiadomień wraca przed
  przeglądem i stary stan schowałby świeży sygnał. Para spoza przeglądu
  (Head of Recruitment i cudze prepy) zostaje widoczna z tytułem i treścią.
- **Do okienka trafiają wszystkie przypomnienia kalendarza**
  (`interview_scheduled`: także screening i termin), bo należą do kategorii.
  Przypomnienie zwija się w wiersz swojego wydarzenia i znika po jego starcie.
  Wydarzenie spoza agendy cyklu (screening, zwykła rozmowa, termin) nie ma
  tu daty, więc start bierzemy z treści („Za 15 minut: …” = utworzenie + 15
  min); bez liczby w treści wiersz żyje najwyżej dobę. Na produkcji 13.10.2026
  w „Nowe” wisiało 8 takich przypomnień sprzed nawet 23 godzin, bo do tej
  poprawki wszystkie żyły dobę.
- **Gaszenie ma własną trasę:** `PUT /api/notifications/interviews/read`
  z `ids` (klik w wiersz albo akcję; także przypomnienie w zastępstwie) albo
  bez ciała (wszystkie własne, jak `read-all`). Nie rób z tego parametru
  `read-all`: backend sprzed zmiany ignoruje nieznany parametr i przy
  rozjeździe wersji w trakcie wdrożenia „Oznacz nowe” zgasiłoby cały dzwonek.
- **Dzwonek pomija kategorię tylko u osób z okienkiem**
  (`hooks/useHasInterviewsWindow.ts` — ten sam warunek co pozycja „Kalendarz”
  w menu, bo trasa cyklu odmawia pozostałym): `listForBell` i
  `markAllReadForBell` z `exclude_interviews`, a `useNotifications` z opcją
  `interviewsInWindow` nie podbija licznika i nie woła dymka dzwonka, tylko
  odświeża trzy klucze zakresów cyklu (`exact`, bez pytań klienta i debriefów
  otwartych okien) i wysyła zdarzenie okna `INTERVIEW_NOTIFY_EVENT`. Opcja jest
  czytana z refa — w zależnościach `connect` rozłączałaby gniazdo.
  `TYPE_CONFIG` typów rozmów i okno feedbacku w dzwonku zostają dla osób bez
  okienka.
- **Typy kategorii zna front jako lustro backendu**
  (`lib/interview-notifications.ts`, test czyta `notification_categories.py`),
  bo ładunek gniazda nie niesie kategorii. Nowy typ w kategorii `interviews`
  = dopisek w obu miejscach.
- **Dymki idą przez `showActionToast`, jak czaty — to nie dymki Jarvisa**
  i nie zużywają jego budżetu. Każde powiadomienie kategorii daje dymek
  „Pokaż” (przypomnienie z linkiem Teams — „Dołącz”); bez dymka, gdy okienko
  jest otwarte. „Rozmowa u klienta skończyła się” nie ma zdarzenia z serwera
  (pierwsze przychodzi po 15 min), więc dymek wychodzi z lokalnie policzonego
  wiersza, raz na przeglądarkę (`claimCallToast`, `localStorage`).
- **Link spotkania otwieramy tylko jako `https:`** (`safeMeetingUrl`): adres
  przychodzi z kalendarza Microsoft 365, także z zaproszeń spoza firmy,
  a `window.open` nie ma osłony, którą React daje `<a href>`.
- **Akcje otwierają istniejące okna w miejscu** (`actionForTodo` →
  `InterviewActionDialogs`, ładowane przez `next/dynamic`, bo pasek stoi na
  każdej stronie). Plików ekranu kalendarza ta zmiana nie rusza — są źródłami
  przewodnika `calendar`.
- **Pasek odpytuje cykl rzadko:** `useInterviewCycle` z
  `WS_BACKED_SAFETY_POLL_MS` i `staleTime` 2 min, odświeżenie przy otwarciu
  okienka; odliczania tyka lokalny zegar (30 s) i budzik na najbliższą granicę
  (`nextWindowBoundary`).
- **Pigułka pilna** (`InterviewsTopbarButton`) tylko przy moim telefonie po
  rozmowie: poniżej `2xl` ikona telefonu i minuty, pełny tekst od 1536 px —
  pasek przy 1280 px z przypiętym menu nie ma miejsca na nazwisko.
- Poza zakresem tej zmiany: gaszenie sygnałów zadań po stronie serwera przy
  wykonaniu akcji (nadal wiszą w „Moich zadaniach”), teksty „kandydatem #id”
  w `notification_triggers.py`, powiadomienie o zaplanowaniu albo przełożeniu
  prepu.
- Harness `/preview/interview-notifications` (części prezentacyjne
  `InterviewsTopbarButton`, `InterviewsPanel` na prawdziwym
  `buildInterviewWindow`; zero zapytań).
- **Pusty stan i „Oznacz nowe” (14.10.2026, po audycie 13.10).** „Nic nie
  czeka” pokazywało się, gdy doszło tylko jedno z dwóch zapytań. Teraz bez
  wierszy okienko pokazuje „Wczytuję rozmowy…”, dopóki drugie źródło nie
  odpowie albo nie padnie; wiersze z pierwszego są widoczne od razu, a pusty
  stan wychodzi tylko wtedy, gdy oba źródła mają dane (awaria jednego to pasek
  „Nie udało się wczytać…”, nie pustka). „Oznacz nowe” stoi tylko przy
  własnych nowych, które okienko pokazuje (`unreadIds` wierszy) —
  powiadomienie schowane (nieaktualne, przypomnienie po starcie wydarzenia)
  nie daje przycisku. Sama akcja dalej gasi wszystkie własne.
