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
