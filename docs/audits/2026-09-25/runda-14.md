# Audyt NEXUS — runda 14 (28.09.2026, domknięcie „Znalezione” z rundy 13)

Baza: `79818095a` (main po PR #1887). Bez nowego audytu — trzy pozycje „Znalezione” z raportu rundy 13.

| Pozycja | Stan | Co zrobiono |
|---|---|---|
| Tokeny w starym formacie (całkowite `iat`) z tej samej sekundy co podłoga sprzed wdrożenia | naprawione w granicy tego, co da się zrobić bez wylogowania ludzi | Całkowite `iat` wybite po wdrożeniu rundy 13 (`_LEGACY_INT_IAT_UNTIL` = 28.09.2026 14:30 UTC) nie mogło powstać legalnie — przy ustawionej podłodze jest odrzucane. Tokeny sprzed wdrożenia wygasają najpóźniej po 30 dniach (`REFRESH_TOKEN_EXPIRE_DAYS`), więc luka zamyka się sama do 28.10.2026. Pomiar na produkcji: 17 z 35 aktywnych kont ma podłogę z ostatnich 30 dni sprzed wdrożenia; natychmiastowe domknięcie wylogowałoby część z nich. Testy `test_session_revocation.py` wybijają tokeny w formacie produkcyjnym (`iat` z ułamkiem) |
| Ekrany z poprawkami responsywności poza harnessami nieprzeklikane | sprawdzone na produkcji | W zalogowanym Chrome, oknie 360 px (pop-up tej samej domeny), tylko odczyt: `/settings/dictionaries` (ze słownikiem „Branża”), `/settings/scoring` (formularz „Nowy profil”, bez zapisu), kontrakt → zakładka Onboarding, lista kontraktów — poziomy przelew 0 px, pola 191–357 px. Czat publicznego CV nie renderuje się (`CV_INTERACTIVE_ENABLED=false`) |
| Nieaktualne `node_modules` w głównym checkoutcie | naprawione w narzędziach | Główny checkout to gałąź innej sesji z 07.2026 — jej `node_modules` jest spójne z jej `package.json`, więc zostało nietknięte. Kopie agentów linkowały się do niego błędnie; osobna kopia `.claude/worktrees/frontend-deps-main` (main + `npm ci`) jest teraz źródłem zależności dla testów frontu w worktree |

## Znalezione

- Chrome w tej sesji nie daje się zwęzić z zewnątrz (`resize_window` bez efektu) — pomiar responsywności na produkcji wymaga pop-upu otwartego prawdziwym kliknięciem.
- Wygląd powiadomienia informacyjnego (`showInfo`) sprawdzony tylko testami, nie na ekranie.
