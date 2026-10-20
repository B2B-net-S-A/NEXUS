/**
 * Klasy układu górnego paska — jedno źródło dla `TopbarV2` i harnessu
 * `/preview/kpi-topbar`, który rysuje replikę paska, żeby zmierzyć licznik
 * celów przy oknie laptopa (1280 × 720 z przypiętym menu). Kopia klas
 * w harnessie rozjechałaby się z paskiem przy pierwszej zmianie odstępów.
 */

export const TOPBAR_HEADER_CLASS =
  "h-12 shrink-0 flex items-center gap-2 sm:gap-3 px-3 md:px-5 bg-background border-b border-border";

/* Okruszki kurczą się (`md:flex-initial`, nie `flex-none`) — na tablecie nie
   wypychają dzwonka i „Dodaj” poza ekran. */
export const TOPBAR_BREADCRUMB_CLASS = "hidden md:flex min-w-0 max-w-[360px] flex-1 md:flex-initial";

/* Od 1280 px wyszukiwarka ma gwarantowane 220 px: zmierzone 13.10.2026 przy
   oknie 1280 px z przypiętym menu i długimi okruszkami — bez minimum licznik
   celów z trzema segmentami zostawiał jej 109 px (sama lupa i skrót).
   Przy 1024–1279 px (menu jako szyna) 140 px: Head of Recruitment z rolą DL,
   z Ligą DL i pigułką „Rozmowy” przy 1024 px nie mieścił się przy 220 px
   o 45 px i cała strona przewijała się w bok (nocne E2E od 14.10.2026). */
export const TOPBAR_SEARCH_CLASS =
  "flex-1 min-w-0 lg:min-w-[140px] xl:min-w-[220px] max-w-md mx-auto flex items-center gap-2 h-8 px-3 rounded-md border border-border bg-muted/50 hover:bg-muted transition-colors text-left text-sm text-muted-foreground";

/* Od 1024 px grupa akcji oddaje miejsce PIERWSZA (przed okruszkami), ale kurczy
   się w niej wyłącznie element oznaczony `data-topbar-shrinks` — licznik celów,
   który chowa wtedy całe segmenty od końca (`KpiTopbarButton`). Reszta dzieci
   dostaje `shrink-0` stąd, nie z własnych klas: przycisk-ikona `w-9` bez
   `shrink-0` ściskał się do 22 px (zmierzone 13.10.2026), a nowa ikona w pasku
   nie może o tym pamiętać. Grupa nie zejdzie więc poniżej „reszta + jeden segment”. */
export const TOPBAR_ACTIONS_CLASS =
  "flex items-center gap-1 sm:gap-2 shrink-0 lg:shrink-[1000] lg:[&>*:not([data-topbar-shrinks])]:shrink-0";
