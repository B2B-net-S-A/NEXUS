# W7-publiczne — raport poprawek (08-public.md)

Ścieżki względem `frontend/`.

| Ustalenie | Stan | Plik:linia | Uwagi |
|---|---|---|---|
| P0-1 CV `/cv/{token}` (backend) | pominięte | — | Inny agent (cv_html_renderer, /cv). |
| P1-1 globalna reguła 14 px | pominięte (zrobione przez innego agenta) | src/app/globals.css | Reguła `text-base md:text-sm` + `pointer:coarse` 16 px już w globals. |
| P1-2 `/apply` pola 14 px / 36 px | zrobione | src/app/apply/[token]/ApplyForm.tsx:399-403 | `inputClass` = `h-11 … text-base sm:h-10 sm:text-sm`; textarea `py-2.5 text-base sm:text-sm`; telefon `inputMode="tel"`, LinkedIn `inputMode="url"` + `autoComplete="url"`; przycisk wysyłki `min-h-11 sm:min-h-10`. |
| P1-3 długa nazwa pliku CV | zrobione | ApplyForm.tsx:307-336 | `min-w-0 flex-1` + `truncate` na nazwie, `shrink-0` na ikonie i „Zmień/Dodaj”, etykieta `min-h-11` + `focus-within:ring-2` (plik jest `sr-only`). |
| P1-4 tytuł `/apply` bez łamania | zrobione | src/app/apply/[token]/page.tsx:104 | `text-2xl sm:text-3xl md:text-4xl break-words hyphens-auto`; to samo (`text-3xl sm:text-4xl md:text-5xl`) na h1 share. |
| P2-1 `min-h-screen` → svh/dvh | zrobione | blocks/AuthShell.tsx:33, login/page.tsx:382, login/microsoft/callback/page.tsx:101,127, apply/layout.tsx:12, share/champion-card/[token]/page.tsx:134, not-found.tsx:6, error.tsx | `min-h-screen` zostaje jako fallback, dopisane `min-h-svh`/`min-h-dvh`. `sign/`, `cv/` — inny agent. |
| P2-2 „pokaż hasło” 16×16, tekst pod ikoną | zrobione | register/page.tsx:237-260, login/reset/page.tsx:125-148 | Przycisk `h-10 w-10 inline-flex` na `right-0.5`, pole `pr-11`. |
| P2-3 przyciski 40 px | zrobione (na stronach auth) | login/page.tsx:302,339; register/page.tsx:276; login/reset:170; login/forgot-password:95 | `h-11 sm:h-10` / `min-h-11 sm:min-h-10`; `ui/button.tsx` nietknięty (inny agent). |
| P2-4 małe linki tekstowe | zrobione | login/page.tsx:310,363; register/page.tsx (3 linki + „wyślij ponownie”); login/reset (2); forgot-password (2); register/verify (2) | `inline-flex min-h-11 items-center … sm:min-h-0` (lub `flex min-h-11`). |
| P2-5 długi e-mail w potwierdzeniu | zrobione | login/forgot-password/page.tsx:50; register/page.tsx:160 | `break-all`. |
| P2-6 `.kr-root { min-height: 100vh }` | zrobione | components/career/career.css:29-33 | `100vh` + `100svh`. |
| P2-7 `themeColor` i jasne `body` | zrobione | app/kariera/layout.tsx (eksport `viewport`), career.css:58-65, CareerTheme.tsx | `themeColor #000`, `colorScheme dark`; `html:has(.kr-root[data-kr-page])` + body na czarno. Atrybut `data-kr-page` tylko z layoutu `/kariera` (prop `page`), żeby harness `/preview/kariera` nie przemalował tła aplikacji. |
| P2-8 tytuł 46 px łamie słowa | zrobione | career.css:.kr-title | `font-size: clamp(34px, 11.5vw, 46px); hyphens: auto` (od 1024 px nadpisane jak dotąd). |
| P2-9 proces i manifest schowane na telefonie | pominięte | CareerJobView.tsx:116-126 | Świadome `kr-desktop-only` z makiety 390 px — to decyzja produktowa, nie błąd układu. Do potwierdzenia z Arturem. |
| P2-10 768–1023 px tekst na pełną szerokość | zrobione | career.css (przed blokiem `min-width:1024px` dla `.kr-main`) | `@media (640–1023px) { .kr-top, .kr-main { max-width: 720px; margin-inline: auto; width: 100% } }`. |
| P2-11 stopka bez łamania adresu + link RODO | zrobione | career.css:.kr-footer / .kr-footer-rodo, CareerFooter.tsx:18 | `overflow-wrap: anywhere`; link `inline-block; padding:12px 0; margin:-12px 0` (cel dotykowy bez zmiany wyglądu). |
| P2-12 `input[type=date]` z `appearance:none` | zrobione | career.css (po `.kr-input`) | `-webkit-appearance/appearance: auto; min-width: 0` tylko dla pola daty. Niepotwierdzone na iOS. |
| P2-13 `.kr-kv-row` bez `min-width:0` | zrobione | career.css:.kr-kv-row > * | `min-width: 0; overflow-wrap: anywhere`. |
| P2-14 podwójny padding | zrobione (apply, share) | apply/[token]/page.tsx:83,130; share/champion-card/[token]/page.tsx:146,172,203,207,235,261 | `px-4 sm:px-6`, karty `p-4 sm:p-6 (md:p-8)`. `/sign` — inny agent. Dodatkowo `PublicLinkUnavailable` `p-4 sm:p-6`. |
| P2-15 stopki `justify-between` | zrobione | apply/[token]/page.tsx:134; share/…/page.tsx:304 | `flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between`. |
| P2-16 nagłówek share ściśnięty | zrobione | share/…/page.tsx:146 | `flex-wrap gap-2`; także nagłówek sekcji Screening `flex-wrap gap-2`, pytania `min-w-0 break-words`, chip roli `max-w-full` + `break-words`. |
| P2-17 brak przewinięcia do błędu | zrobione | ApplyForm.tsx:73-84,145,199,405-411 | `aria-invalid` + `aria-describedby` na każdym polu (`invalidProps`), po odmowie (klient i 422 z API) fokus na pierwszym `[aria-invalid="true"]`. |
| P2-18 `/sign` iframe PDF | pominięte | — | Inny agent (`/sign`). |
| P2-19/20 `/cv`, `/cv/i` | pominięte | — | Inny agent (`/cv`, backend html_export). |
| global-error bez viewportu | zrobione | src/app/global-error.tsx:31-35 | `<head><meta name="viewport" …></head>`, padding 24, przycisk min. 44 px. |
| not-found 404 9rem, przycisk h-10 | zrobione | src/app/not-found.tsx:6,19,23,38 | `text-[6rem] sm:text-[9rem]`, ikona `w-12 sm:w-16`, `h-11 sm:h-10`. Treść „Wróć do dashboardu” bez zmian (poza responsywnością). |
| error.tsx | zrobione | src/app/error.tsx:31-45 | `p-4 sm:p-8`, `min-h-dvh`, `pre max-w-full`, przycisk `min-h-11`. |
| Szkielet pulpitu na stronach publicznych | zrobione | nowe: src/app/kariera/loading.tsx, src/app/apply/loading.tsx, src/app/share/loading.tsx | Kariera: `TerminalChrome` + „$ ładowanie…” w motywie; apply/share: prosty „Ładowanie…”. Efekt niepotwierdzony w przeglądarce. |
| Brakujące spacje `{""}` | zrobione | share/…/page.tsx:161 („Ważne do ”), :193 („stanowisko: ”); apply/[token]/page.tsx:116 | `{" "}`. |
| Tło „ambient glow” share (złe CSS) | zrobione | share/…/page.tsx:140 | `hsl(var(--primary) / 0.15)` (token to trójka HSL). |
| Zagnieżdżone `<label>` w `/apply` | zrobione | ApplyForm.tsx:307-313, Field:419-446 | `Field` ma `as="div"` dla CV; plik ma `aria-labelledby="apply-cv-label apply-cv-name"`. |
| `/engagement` | pominięte | — | Inny agent. |

## Testy
- `src/app/apply/[token]/__tests__/ApplyForm.test.tsx`: dodane 2 testy — fokus i `aria-invalid`/`aria-describedby` na pierwszym błędnym polu po odmowie; brak `label label` + `aria-labelledby` pola CV + `truncate` na długiej nazwie pliku. Żaden istniejący test nie wymagał zmiany.

## Poza zakresem
- `src/components/ui/button.tsx` (`lg` = h-10) — zmiana globalna należy do agenta ui/*; na stronach auth nadpisane klasą.
- `src/app/kariera/*`: `.kr-log-title` (40 px, 404/zamknięta/błąd) mogłaby dostać ten sam `clamp` co `.kr-title` — niezgłoszone w raporcie, pominięte.
- `src/app/layout.tsx` (root) — tło `body` pod karierą rozwiązane CSS-em w `career.css`, bez zmiany roota.

## Sprawdzenia
- `npx vitest run src/app/apply src/components/career src/app/preview/kariera src/app/login src/app/register src/components/public` → 7 plików, 59 testów zielone (+2 nowe → apply 19/19).
- `npx eslint` na wszystkich plikach zakresu → bez błędów i ostrzeżeń.
- `npx tsc --noEmit -p .` → jedyne błędy w `src/components/marketplace/MarketplaceTable.tsx` (plik innego agenta, w trakcie edycji); w plikach zakresu zero.
- Przeglądarka: niepotwierdzone (zgodnie z zasadami bez `next dev`/`build`) — iOS: pole daty, `themeColor`, loading.tsx.
