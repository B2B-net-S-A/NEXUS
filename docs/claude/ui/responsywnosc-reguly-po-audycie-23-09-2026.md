# Responsywność — reguły po audycie 23.09.2026

Audyt i lista ustaleń: `docs/responsiveness-audit-2026-09-23/`. Reguły wspólne
żyją w `frontend/src/app/globals.css` (blok „RESPONSYWNOŚĆ”, poza warstwami):

- **Wysokość ekranu to `dvh`, nigdy `h-screen`/`100vh`** — na telefonie `vh`
  liczy wysokość bez paska przeglądarki i dół strony się pod nim chował
  (shell `AppShellV2` jest `h-dvh`; pilnuje `responsive-guards.test.ts`).
- **Pola mają 16 px na dotyku** (reguła `@media (pointer: coarse)`), bo iOS
  przybliża stronę przy fokusie w polu < 16 px. Klasa `text-sm` na polu jej
  nie zmienia — nie dokładaj wyjątków.
- **Akcja widoczna po najechaniu = `pointer-fine:opacity-0
  pointer-fine:group-hover:opacity-100 focus-within:opacity-100`.** Goły
  `opacity-0 group-hover:opacity-100` chowa przycisk na dotyku na zawsze
  (w Tailwind v4 `hover:` działa tylko z myszą) — wywala strażnika.
- **Małe ikony dostają `hit-area`** (pole trafienia 16 px szersze) albo
  `pointer-coarse:` rozmiar; `hit-area` ustawia `position: relative`, więc na
  elemencie `absolute` użyj `pointer-coarse:after:absolute after:-inset-2`.
  `Button` `sm`/`icon` ma 40 px na dotyku. Tekst `text-[10px]` ma na dotyku 11 px.
- **Tabela = `overflow-x-auto` + `min-w-[…]` + przyklejona 1. kolumna**, nigdy
  `overflow-hidden` wokół tabeli (ucinał kolumnę akcji). Bez widoków kart
  (decyzja 23.09.2026).
- **Listy wypełniają duży monitor (02.10.2026, zgłoszenie: w Traffit kolumny
  szły na cały ekran, u nas lista kończyła się na 1400 px).** Rekrutacje,
  Kandydaci, Klienci, Kontrakty i Finanse nie mają limitu szerokości — idą do
  krawędzi okna jak pulpit (decyzja Artura; pierwsza wersja z limitem 2400 px
  zostawiała puste boki na pomniejszonym ekranie). Nie dokładaj `max-w-*`
  ani `mx-auto` na stronie listy. Dane stojące drobnym drukiem
  pod główną wartością (klient pod tytułem, rekrutacja pod klientem, „umowa
  do” pod startem) dostają własne kolumny, gdy TABELA ma ≥ 1700 px — klasy
  `WIDE_ONLY_CELL` / `WIDE_HIDDEN` i `@container` na opakowaniu tabeli, nie
  próg okna (menu, dok i panel szczegółów zabierają miejsce). Poniżej progu
  układ zwarty bez zmian. Kolumna szeroka i jej drobny druk są w DOM naraz
  (jsdom nie liczy CSS) — testy rozróżniają je po klasie. **Lista rekrutacji
  ma od 02.10.2026 jeden układ dla każdej szerokości** (decyzja Artura: osobny
  wygląd na duży monitor odrzucony) — nie dokładaj tam kolumn szerokiej tabeli.
- **Widżet w kafelku/doku/oknie układa się po szerokości KONTENERA**
  (`@container` + `@lg:`), nie okna — kafelek pulpitu ma 400–600 px na
  szerokim ekranie.
- **Pasek boczny bez zapisanej preferencji jest przypięty dopiero od 1280 px**
  (`useSidebarPinned`), a rozwinięcie po najechaniu reaguje tylko na mysz.
- **Kalendarz poniżej `md` to widok jednego dnia** (CSS chowa pozostałe
  kolumny, `?event=` wybiera dzień wydarzenia).
- Nocny projekt `preview-chromium` uruchamia `e2e/responsive-preview.spec.ts`:
  każdy harness `/preview/*` przy 360/390/768/1024/1280 bez poziomego scrolla
  strony. Nowy harness dopisz do listy. Mierz `setViewportSize` na Chrome
  desktopowym — emulacja telefonu poszerza układ i maskuje przelew.
- **Laptop z Windows to docelowy ekran, nie szeroki Mac (28.09.2026).**
  Skalowanie 125–150% daje przeglądarce 1280–1536 × 650–860 px (zmierzone:
  Mac Artura 2666 × 1229, laptop rekrutera ≈ 1280 × 650). Nagłówek i filtry
  rosły tam w dół i tablica rekrutacji zaczynała się na 73% wysokości. Zasada:
  **przy 1280 × 720 główna treść (tablica, tabela) zaczyna się w górnych 60%
  okna** — filtry w jednym rzędzie, rzadsze pod „Więcej filtrów”, liczby
  powtórzone w kilku miejscach dopiero od `2xl`. Pilnuje test „okna laptopów
  z Windows” w `e2e/responsive-preview.spec.ts` (1280×720, 1366×768, 1536×864;
  harnessy bez powłoki dostają ramkę CSS 240 px + 48 px), harness tablicy
  z powłoką: `/preview/job-detail`. Zwarty układ poniżej `2xl`, na liście
  kandydatów poniżej `min-[1800px]` (1536 × 864 to też niski ekran). Każda
  zmiana UI: przeklikaj też przy 1280 × 720, nie tylko na dużym monitorze.
