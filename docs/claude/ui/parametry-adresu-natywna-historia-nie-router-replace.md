# Filtr albo zakładka w adresie: `useUrlWriter`, nie `router.replace(…, { scroll: false })` (12.10.2026)
<!-- indeks: router Next przewija stronę na górę na produkcji -->

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
  zapisuj przez `useUrlWriter()` z `lib/url-selection.ts`: `replaceUrl(href)`
  albo `pushUrl(href)`, gdy „Wstecz” ma cofać ten krok. Pod spodem jest
  `window.history.replaceState(null, "", href)` / `pushState` — Next przenosi
  taki adres do `useSearchParams` i `usePathname` bez zapytania do serwera
  i bez przewijania, a „Wstecz” po `pushUrl` działa jak po `router.push`.
- Stan ma być `null`: z `window.history.state` (ma znacznik `__NA`) Next
  uznaje wywołanie za własne i `useSearchParams` nie zobaczy zmiany — tak
  działa `writeUrlParams` z tego samego pliku, dobre tylko tam, gdzie ekran
  trzyma stan lokalnie.
- **Inna ścieżka niż bieżąca idzie przez router** — hook sam to rozpoznaje.
  Dlatego komponenty z adresem wpisanym na sztywno (`/clients/{id}`,
  `/insights`, `/contracts/b2b-generator`) w harnessach `/preview/*` nadal
  używają routera; drogę natywną w harnessie pokazują tylko te, które budują
  adres z bieżącej ścieżki (profil kandydata, lista klientów, pulpit).
- **Zabezpieczenie w hooku:** Next przejmuje `history` dopiero w efekcie
  routera, czyli po efektach dzieci z tej samej klatki. Zapis z efektu
  w pierwszej klatce poza `<Suspense>` zostawiłby wpis bez stanu routera
  („Wstecz” przestaje działać), więc hook sprawdza `history.state.__NA` po
  zapisie i w takim razie oddaje adres routerowi. Treść strony stoi pod
  `loading.tsx`, więc dziś to się nie zdarza — ale nie zdejmuj tego warunku.
  `pushUrl` na adres, który już stoi, nie dokłada wpisu historii.
- `router.replace` / `router.push` wprost zostają do przejścia na inną stronę
  albo gdy komponent serwerowy strony czyta `searchParams`.
- **Wyjątek: `app/jobs/[id]/page.tsx`.** Dwie korekty adresu tuż po wejściu
  (przepisanie starego kształtu `?tab=` i zdjęcie `?candidate=`) zostały na
  `router.replace`. Strona pisze resztę adresu przez `writeUrlParams`, czyli
  poza wiedzą Next, a korekty liczą się z jego widoku adresu; zapis natywny
  nadpisywał w tej samej klatce to, co chwilę wcześniej zapisał panel (wyszło
  w `JobDetailPage.routing.test.tsx`). Obie
  odpalają się przy wejściu na stronę, więc przewinięcie i tak jest na górze.
- **Stan na 12.10.2026:** `RequestBoard` (#2128) i pozostałe 28 wywołań
  w 16 plikach (zakładki profilu klienta, kandydata i kontraktu, Insights,
  generator umów B2B i dokumenty, lista klientów, Akademia, marketplace,
  „Moi ludzie”) są przeniesione. `grep -rnE "scroll:\s*false" frontend/src`
  ma zwracać tylko hook, wyjątek wyżej i testy.
