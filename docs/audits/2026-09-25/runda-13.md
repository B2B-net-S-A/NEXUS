# Audyt NEXUS — runda 13 (28.09.2026, domknięcie „Znalezione” z rundy 12)

Baza: `6cfb45c8d` (main po PR #1884–#1886). Bez nowego audytu — naprawa pozycji „Znalezione” z raportu rundy 12, na polecenie Artura. 4 agentów + poprawki koordynatora + przegląd kodu + pełne CI.

## Co naprawiono

| Pozycja | Stan | Co zrobiono |
|---|---|---|
| Unieważnianie tokenów z dokładnością do sekundy | naprawione | Nowe tokeny mają `iat` z mikrosekundami, `token_is_revoked` porównuje je dokładnie. Tokeny sprzed wdrożenia (całkowite `iat`) — nadal po pełnych sekundach, żeby wdrożenie nikogo nie wylogowało. Podłoga `tokens_valid_after` z zegara aplikacji (nie `func.now()` = początek transakcji) przy zmianie hasła, resecie linkiem, resecie przez admina i unieważnieniu zakresu DL |
| Zapisane wyszukiwania z filtrem umiejętności bez własnego powodu ponownej akceptacji | naprawione | Kod `screening_skills` w `diff.rules`, zdanie po polsku w oknie akceptacji |
| Wzorce przelewania poza harnessami | naprawione | 20 pól `flex-1` bez szerokości (`w-0`, także `<select>`) w 16 plikach, 7 przewijanych kontenerów bez `relative` z `sr-only`/`absolute` w środku; dwa strażniki w `responsive-guards.test.ts` (parser TypeScript, nie regex) |
| Powiadomienia bez typu „informacja” | naprawione | `showInfo` w `components/Toast.tsx` (rola `status`, tokeny `info`); „Brak rekrutacji do wysłania w shortliście” i „Wszystkie wybrane szablony są już zaaplikowane” — informacja, nie błąd |

## Znalezione, poza zakresem

- Tokeny w starym formacie (całkowite `iat`) wybite w tej samej sekundzie co podłoga postawiona przed wdrożeniem działają do wygaśnięcia (refresh do 30 dni) — świadomy kompromis, żeby wdrożenie nie wylogowało sesji z rundy 12 i logowań SSO.
- Poprawki wzorca `relative` na kontenerach tabel są zgodne ze wzorcem z rundy 12 (TraineesPanel), ale przelew przed zmianą zmierzony tylko na `/preview/table` (0 px). Ekrany spoza harnessów nieprzeklikane.
- Strażnik responsywności nie widzi klas dokładanych wewnątrz innych komponentów (np. ukryte pola Radix).
- Wspólne `frontend/node_modules` głównego checkoutu jest nieaktualne (brak `pdfjs-dist`, `react-grid-layout`) — lokalne testy w worktree agentów bez własnego `npm ci` padają bez związku ze zmianą.
