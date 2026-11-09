# Harnessy `/preview/*` poza buildem produkcyjnym · flaga tylko dla E2E, limit liczby stron

Audyt z 07.11.2026 (pozycja D4). Strony `/preview/*` z fikcyjnymi danymi służą
wyłącznie testom, więc obraz produkcyjny ich nie zawiera.

- `frontend/Dockerfile` usuwa `src/app/preview` przed `next build`, chyba że
  build dostał `NEXT_PUBLIC_PREVIEW_PUBLIC=1`. Flagę przekazuje tylko
  `docker-compose.e2e.yml`, na którym chodzi `preview-chromium`.
- Krok `Build` w `ci.yml` usuwa je tak samo, żeby wykrył kod produkcyjny
  zależny od harnessu.
- `next dev`, Vitest i `tsc` dalej widzą te pliki. Na produkcji i na stagingu
  z obrazu produkcyjnego adres `/preview/*` daje 404 po zalogowaniu.
- Nowa zmiana UI nie dostaje nowego harnessu: makietę pokazuje się na stagingu
  (`makiety-na-stagingu.md`). Limit stron jest w
  `frontend/src/__tests__/preview-harness-limit.test.ts` i może tylko maleć.
