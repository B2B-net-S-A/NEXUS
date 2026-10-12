# Filtr albo zakładka w adresie: natywna historia, nie `router.replace(…, { scroll: false })` (12.10.2026)
<!-- indeks: zmiana samych parametrów adresu przez router Next przewija stronę na górę na produkcji -->

Zgłoszenie Artura 12.10.2026: w kafelku „Requesty i obłożenie” każda zmiana
filtra przewijała pulpit na górę. Pomiar na produkcji: `<main>` 1000 → 24 px
na `/dashboard`, 1834 → 0 px w harnessie `/preview/custom-dashboard`.

- **Przyczyna jest w routerze Next 15.5, nie w naszym kodzie.** Gdy zmieniają
  się same parametry adresu (ta sama ścieżka), a w drzewie jest `loading.tsx`
  (u nas główny `app/loading.tsx`, czyli każdy ekran), router bierze ścieżkę
  „aliased prefetch” (`handleAliasedPrefetchEntry`). Ta ścieżka nie przenosi
  `shouldScroll`, więc `scroll: false` przepada i `ScrollAndFocusHandler`
  przewija do pierwszego elementu strony, jeśli jego górna krawędź jest poza
  oknem (wystarczy ok. 80 px przewinięcia). Przy okazji każda taka zmiana
  wysyła do serwera zapytanie RSC, którego nikt nie potrzebuje.
- **Tylko zbudowana aplikacja.** Aliasowanie jest wyłączone przy
  `NODE_ENV=development`, więc `next dev` i Vitest tego nie pokażą. Sprawdzaj
  na produkcji albo na zbudowanym stosie (`e2e.yml`, projekt `preview-chromium`,
  test „filtr … nie przewija strony” w `e2e/responsive-preview.spec.ts`).
- **Reguła:** stan widoku trzymany w adresie (filtr, zakładka, strona listy)
  zapisuj przez `window.history.replaceState(null, "", href)` albo
  `pushState`, gdy „Wstecz” ma cofać ten krok. Next przenosi taki adres do
  `useSearchParams` i `usePathname` bez zapytania do serwera i bez przewijania.
  Pierwszy argument ma być `null`: z `window.history.state` (ma znacznik
  `__NA`) Next uznaje wywołanie za własne i `useSearchParams` nie zobaczy
  zmiany — tak działa `writeUrlParams` z `lib/url-selection.ts`, dobre tylko
  tam, gdzie ekran trzyma stan lokalnie.
- `router.replace` / `router.push` zostają do przejścia na inną ścieżkę albo
  gdy komponent serwerowy strony czyta `searchParams`.
- **Stan na 12.10.2026:** poprawiony jest `RequestBoard` (kafelek i `/jobs/daily`).
  Ten sam wzorzec ma jeszcze 30 wywołań w 17 plikach (zakładki profilu klienta,
  kandydata i kontraktu, Insights, generator umów B2B, lista klientów,
  Akademia) — `grep -rnE "scroll:\s*false" frontend/src`. Skaczą tak samo, gdy
  ekran jest przewinięty; przy zmianie takiego miejsca przenieś je na natywną
  historię i popraw test, który sprawdza `router.replace`.
