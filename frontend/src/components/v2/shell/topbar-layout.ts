/**
 * Klasy układu górnego paska — jedno źródło dla `TopbarV2` i harnessu
 * `/preview/kpi-topbar`, który rysuje replikę paska, żeby zmierzyć licznik
 * celów przy oknie laptopa (1280 × 720 z przypiętym menu). Kopia klas
 * w harnessie rozjechałaby się z paskiem przy pierwszej zmianie odstępów.
 */

/* Pasek przewija się w bok tylko wtedy, gdy nie zmieści wszystkiego naraz (P0,
   Nowości, Nieobecni i pigułki w jednej chwili), bez widocznego suwaka. Panele
   ikon są w portalach, więc `overflow` ich nie ucina. Reguły przy 1280 px:
   docs/claude/ui/gorny-pasek-przy-1280.md. */
export const TOPBAR_HEADER_CLASS =
  "h-12 shrink-0 flex items-center gap-2 min-[1800px]:gap-3 px-3 md:px-5 overflow-x-auto overflow-y-hidden [scrollbar-width:none] bg-background border-b border-border";

/* Okruszki kurczą się (`md:flex-initial`, nie `flex-none`) — na tablecie nie
   wypychają dzwonka i „Dodaj” poza ekran. */
export const TOPBAR_BREADCRUMB_CLASS = "hidden md:flex min-w-0 max-w-[360px] flex-1 md:flex-initial";

/* Od 1280 px wyszukiwarka ma gwarantowane 200 px: zmierzone 13.10.2026 przy
   oknie 1280 px z przypiętym menu i długimi okruszkami — bez minimum licznik
   celów z trzema segmentami zostawiał jej 109 px (sama lupa i skrót). Do 04.11.2026
   było tu 220 px; podpowiedź i przy nich była ucięta, a 20 px brakowało ikonom.
   Przy 1024–1279 px (menu jako szyna) 140 px: Head of Recruitment z rolą DL,
   z Ligą DL i pigułką „Rozmowy” przy 1024 px nie mieścił się przy 220 px
   o 45 px i cała strona przewijała się w bok (nocne E2E od 14.10.2026). */
export const TOPBAR_SEARCH_CLASS =
  "flex-1 min-w-0 lg:min-w-[140px] xl:min-w-[200px] max-w-md mx-auto flex items-center gap-2 h-8 px-3 rounded-md border border-border bg-muted/50 hover:bg-muted transition-colors text-left text-sm text-muted-foreground";

/* Od 1024 px grupa akcji oddaje miejsce PIERWSZA (przed okruszkami), ale kurczy
   się w niej wyłącznie element oznaczony `data-topbar-shrinks` — licznik celów,
   który chowa wtedy całe segmenty od końca (`KpiTopbarButton`). Reszta dzieci
   dostaje `shrink-0` stąd, nie z własnych klas: przycisk-ikona `w-9` bez
   `shrink-0` ściskał się do 22 px (zmierzone 13.10.2026), a nowa ikona w pasku
   nie może o tym pamiętać. Grupa nie zejdzie więc poniżej „reszta + jeden segment”.
   `min-w-max` z tego samego powodu: tekst, który da się złamać („P0 teraz”), zaniżał
   najmniejszą szerokość grupy o 11 px i ostatni przycisk wystawał z niej (04.11.2026).
   Odstęp 4 px do 1799 px: przy 1280 px dziesięć odstępów to 40 px paska. */
export const TOPBAR_ACTIONS_CLASS =
  "flex items-center gap-1 min-[1800px]:gap-2 shrink-0 lg:shrink-[1000] lg:[&>*:not([data-topbar-shrinks])]:shrink-0 lg:[&>*:not([data-topbar-shrinks])]:min-w-max";

/* „+” jest zawsze cały w oknie: gdy pasek się przelewa, zostaje przy prawej
   krawędzi, a reszta przewija się pod nim. `right-0`, bo `sticky` Chrome liczy od
   krawędzi treści paska (po `px-*`): `right-5` przesuwało „+” o 20 px na sąsiada.
   Cień w kolorze tła zasłania ikony przewijane w marginesie na prawo od „+”. Do 1799 px
   sama ikona (36 px zamiast 81 px), słowo „Dodaj” od 1800 px i w nazwie przycisku. */
export const TOPBAR_ADD_BUTTON_CLASS =
  "sticky right-0 z-10 h-9 w-9 px-0 pointer-coarse:min-w-10 shadow-[10px_0_0_10px_var(--color-background)] min-[1800px]:h-8 min-[1800px]:w-auto min-[1800px]:px-3";

export const TOPBAR_ADD_LABEL_CLASS = "hidden min-[1800px]:inline";
