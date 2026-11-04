# Otwarta karta sama przechodzi na nową wersję — raport

Data: 12.10.2026. Zgłoszenie Artura: Delivery Leadzi widzą stary ekran
tworzenia rekrutacji i stare błędy przy wpisywaniu wymagań, admin widzi nowy.
Decyzja: „musi cały czas to się robić automatycznie”.

## Przyczyna

| Co sprawdzono | Wynik |
|---|---|
| Czy serwer podaje dwie wersje | nie — jeden kontener frontu, `version.json` 16 razy z rzędu ten sam SHA |
| Czy ekran zależy od roli | nie — `/jobs/new` to ten sam komponent dla admina i Delivery Leada, bez rozgałęzień |
| Czy późniejsze scalenia cofnęły zmianę | nie — pliki nowego ekranu są na `main`, ostatnia zmiana w nich to #2129 (kosmetyka) |
| Nagłówki plików JS | `public, max-age=31536000, immutable`, Cloudflare `HIT` — stare pliki nigdy nie znikają dla starej karty |
| Nagłówki dokumentu strony | `s-maxage=31536000`, bez zakazu przechowywania — karta przywrócona przez przeglądarkę bierze stary dokument |
| Czy aplikacja wykrywa nową wersję | nie — jedyne zabezpieczenie (`chunk-reload`) czeka na błąd ładowania pliku, którego przy rocznej pamięci nie ma |

Wniosek: karta otwarta przed wdrożeniem działa na starej wersji bez końca.
Na komputerach Delivery Leadów niepotwierdzone bezpośrednio (nie mam do nich
dostępu) — potwierdza to odświeżenie strony u nich.

## Co zrobiono

- `AppVersionGuard`: karta co minutę, po powrocie i przy zmianie strony pyta
  o wersję i przeładowuje się sama, gdy nic nie przepadnie; blokuje ją tylko
  praca w toku (wpisany tekst, zmienione pole, otwarte okno, trwający zapis).
- Dokument strony z `Cache-Control: no-store`.
- Reguła: `docs/claude/podstawy/wersja-frontu-w-otwartej-karcie.md`.

## Stan i dowody

| Część | Stan | Dowód |
|---|---|---|
| Wykrywanie wersji | zrobione | `app-version.test.ts` (6): inny SHA, brak SHA, awaria odpowiedzi, jedno przeładowanie na wersję |
| Automat | zrobione | `AppVersionGuard.test.tsx` (14), każdy najpierw czerwony: karta w tle, minuta spokoju, powrót do karty, zmiana strony, wpisany tekst, tekst bez klawiatury, pole zmienione bez człowieka, otwarte okno, trwający zapis, brak pętli, osoba z zewnątrz, podgląd |
| Przeglądarka | sprawdzone lokalnie | Playwright na lokalnym podglądzie z podstawionym SHA i `version.json` (1280×720): oglądanie → karta przeładowała się sama; wpisany tekst → 0 przeładowań i komunikat, przejście na inną stronę → przeładowanie; karta w tle → przeładowanie; ta sama wersja 10 min → cisza; osoba bez konta → cisza; telefon 390 px → komunikat mieści się, 0 px poziomego scrolla |
| Nagłówek dokumentu | zrobione, na produkcji do sprawdzenia po wdrożeniu | `security-headers.test.ts` (2); Next 15.5 nie nadpisuje `Cache-Control` ustawionego w konfiguracji (`send-payload.js`: „If cache control is already set…”) |
| Testy frontu | zielone | `vitest --changed origin/main`: 4 pliki, 36 testów; `npm run type-check`, ESLint zmienionych plików |

## Niepotwierdzone i poza zakresem

- Karty otwarte przed tym wdrożeniem nie mają mechanizmu w sobie: każda osoba
  musi raz odświeżyć stronę (F5). Od tej chwili dzieje się to samo.
- Stan strony trzymany tylko w pamięci, powstały bez zmiany pola i bez okna,
  przepada przy przeładowaniu po minucie spokoju (opis w regule).
- Strona, na której ktoś coś wpisał, zostaje na starej wersji do przejścia na
  inną stronę — świadomie, bo przeładowanie kasowałoby tekst.
