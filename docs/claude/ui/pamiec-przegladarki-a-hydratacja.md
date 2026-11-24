# Pamięć przeglądarki w pierwszym renderze = bramka `useHydrated()`

Strony NEXUSA renderują się na serwerze (layout czyta nonce CSP z nagłówków),
a serwer nie ma `sessionStorage` ani `localStorage`. Komponent, którego
pierwszy render zależy od takiej pamięci (inicjalizator `useState`, odczyt
w ciele komponentu), renderuje na serwerze co innego niż w przeglądarce.
Wtedy React zgłasza błąd hydratacji #418 i renderuje stronę od nowa.

Przykład z 15.11.2026: lista `/candidates` czytała ostatnie wyszukiwanie karty
(`readListSearch()`, `lib/search-memory.ts`) w inicjalizatorze stanu. Goły
`/candidates` załadowany od zera (odświeżenie, link spoza aplikacji, wyjście
z Poligonu) miał w przeglądarce baner „Wróciłeś do swojego wyszukiwania”,
którego nie było w HTML-u z serwera. e2e Poligonu (`e2e/poligon-walk.spec.ts`)
padało przez to losowo i wyrzucało z kolejki merge'ów niezwiązane PR-y.

Jak robić:
- Odczyt pamięci w efekcie (jak `useRailCollapsed` w `OpenTabsRail.tsx`) albo
  bramka `useHydrated()` z `hooks/useHydrated.ts`. Do końca hydratacji stoi
  szkielet; przy nawigacji w aplikacji hook od razu zwraca `true`, więc nie ma
  mignięcia. Tak jest zrobiony `CandidatesListV2`.
- `typeof window === "undefined"` w renderze nie wystarcza. Daje inny wynik na
  serwerze i w przeglądarce, czyli właśnie tę niezgodność.
- Test: `renderToString` bez pamięci, potem zapis do pamięci i `hydrateRoot`
  z `onRecoverableError`. Wzór: test „goły adres załadowany od zera” w
  `components/v2/pages/__tests__/CandidatesListV2.test.tsx`.
- `next dev` często tego nie pokazuje. Rozjazd widać na buildzie produkcyjnym
  (`next build` + `next start`).

## Cache react-query wypełniony przez powłokę

Ta sama bramka dotyczy ekranu, którego pierwszy render zależy od cache'u
react-query. `app/loading.tsx` stawia granicę Suspense wokół każdej strony,
a React hydratuje jej treść osobno, już po zatwierdzeniu powłoki. Efekty
powłoki zdążą wtedy pobrać dane, a serwer zawsze renderuje z pustym cache'em.

- Okruszek (`BreadcrumbV2`, `DynamicLabel`) czyta nazwę pod kluczem strony,
  żeby nie pobierać jej drugi raz: `["job", id]` dla `/jobs/[id]` (#2824)
  i `["candidate", id]` dla profilu kandydata (24.11.2026). Oba ekrany trzymają
  stan ładowania do `useHydrated()`. Nowy wspólny klucz okruszka = taka sama
  bramka na ekranie.
- Na Poligonie odpowiedź przychodzi z zestawu w pamięci, bez sieci, więc
  przy pełnym wczytaniu wyprzedza hydratację strony (React #418 na profilu
  ćwiczebnym, 24.11.2026). Na prawdziwych danych idzie przez sieć i zwykle
  przychodzi później, dlatego błąd widać rzadko.
- Kolejność zależy od tego, kiedy dojdzie plik JS strony. `next dev` (wolny JS)
  pokazuje rozjazd od razu, a z diffem drzewa w treści błędu. Lokalny build
  produkcyjny bywa szybszy od okruszka, więc test E2E wstrzymuje plik strony,
  aż okruszek pokaże nazwę („odświeżony profil” w `e2e/poligon-walk.spec.ts`).
