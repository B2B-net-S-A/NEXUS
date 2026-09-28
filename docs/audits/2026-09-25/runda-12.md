# Audyt NEXUS — runda 12 (28.09.2026, domknięcie „Znalezione” z rundy 11)

Baza: `ab01059fb` (main po PR #1877 i #1878–#1882). Bez nowego audytu — naprawa wszystkich pozycji „Znalezione” z raportu końcowego rundy 11, na polecenie Artura. 4 agentów naprawczych + przegląd kodu + pełne CI.

## Co naprawiono

| Pozycja | Stan | Co zrobiono |
|---|---|---|
| Dwa ekrany czytały CV tylko z bieżącego etapu | naprawione | Wspólny hook `useStageBrandedCv` + `pairSourceStageId` (`lib/cv-to-client.ts`) w karcie „CV do klienta”, warsztacie wysyłki (`CvHandoffWorkbench` — stan CV, link dla klienta, lista i odwołanie linków) i zakładce „Rekrutacje” profilu |
| Umiejętności ze screeningu poza zakresem „Umiejętności”, filtrem i wycinkami | naprawione | Zakres `q_scope=skills` (obie ścieżki: regex i korpus złożony), filtr umiejętności **tylko v2** (v1 — ten sam SQL, test porównuje napis), wycinki. Jedno źródło: `keyword_corpus._screening_skills_from` |
| Natywne `alert()` | naprawione | 17 wywołań → `showError` z `useToast`; strażnik `native-confirm-guard.test.ts` odrzuca `window.alert` |
| Request „Do przejrzenia” z championem miał status „champion” | naprawione | `request_status_expr`: champion tylko przy `work_state = 'searching'` (jak `request_stage_expr` i `visible_state`) |
| Wylogowanie po zmianie hasła (niepotwierdzone w r10/r11) | potwierdzone i naprawione | `change_password` unieważniał też bieżący token i odpowiadał 204. Teraz 200 z nową parą tokenów (bez `fpc`); inne sesje dalej unieważnione; front zapisuje nowy token (`lib/password-change-session.ts`) |
| Nocny test `/preview` (niepotwierdzone) | sprawdzone i naprawione | Nocny `preview-chromium` padał od 25.09 na 5 harnessach z poziomym scrollem: `sr-only` bez `relative` w tabeli praktykantów (błąd także na produkcji), pola `flex-1` bez `w-0` (minimum z `size=20` zależne od fontu Linuksa — także na produkcji), dwa błędy samych harnessów. Lokalnie 62/62 |

## Decyzje Artura

| Temat | Decyzja |
|---|---|
| „Mamy championa” kliknięte na requeście „Do przejrzenia” | Zostaje jak jest — oznaczenie zapisuje się, widać je po przestawieniu stanu na „Szukamy” |

## Znalezione, poza zakresem

- `token_is_revoked` porównuje pełne sekundy — token wybity w tej samej sekundzie co zmiana hasła nie jest unieważniany (stare ograniczenie, dotyczy też resetu hasła linkiem).
- Zapisane wyszukiwanie z listy z filtrem umiejętności, migrowane v1 → v2, może dać inny wynik (osoby z umiejętnością tylko ze screeningu) — trafi do ponownej akceptacji z powodem ogólnym, bez własnego kodu powodu.
- Wzorce z harnessów (`sr-only` w przewijanej tabeli bez `relative`, pole `flex-1` bez szerokości w `<fieldset>`) mogą być w innych plikach poza harnessami objętymi testem.
- Toast nie ma typu „info” — komunikat „Brak rekrutacji do wysłania w shortliście.” idzie jako błąd.
- `authApi.changePassword` we froncie bez konsumenta (martwy kod).
