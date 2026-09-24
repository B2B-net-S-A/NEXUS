# W4 — Kontrakty, generatory, publiczne CV / podpis / engagement

Źródła: `05-contracts-generators.md` (całość), z `08-public.md` pozycje `/cv/[token]`, `/cv/i`, `/sign`, `/engagement` (P0 renderer, wysokości ramek, textarea + podwójny padding), z `10-runtime.md` nagłówek `ContractsListV2` (harness `contracts-consolidation`).

## Ważne ustalenie przy P0 (publiczne CV)

`sanitize_cv_html` (`backend/app/services/html_sanitizer.py`, `_VisibleCVMarkup`) **wycina `<head>` i `<style>`** z HTML-a, który publiczne endpointy serwują jako `cv_html` (`public_share.py:292`, `:515` → `approved.content_html`, też po sanitizacji). Sprawdzone w kontenerze: HTML z `_generate_cv_html` ma arkusz (5984 zn., zawiera nowe `@media`), po sanitizacji `'<style' in s == False`, klasy (`cv-body`) zostają. Czyli na `/cv/{token}` i `/cv/i/{token}` klient dostaje dziś CV **bez arkusza stylów** (zwykły przepływ blokowy, tylko style inline) — siatka 230 px + 1fr z audytu się tam nie stosuje. P0 w tej postaci dotyczy plików z pełnym arkuszem (eksport HTML `render_interactive_html`, podglądy wewnętrzne). Poprawki zrobiłem zgodnie z zadaniem (backend + doklejanie stylu we froncie — nieszkodliwe, zadziała, gdy arkusz kiedyś wróci), ale **osobnym problemem jest brak stylów w publicznym CV** — do decyzji (poza zakresem responsywności).

## Tabela

| ustalenie | stan | plik:linia | uwagi |
|---|---|---|---|
| P0-1 renderer brandowanego CV bez `@media` | zrobione | `backend/app/services/cv_html_renderer.py:453` | `@media (max-width:640px)`: 1 kolumna, sidebar z dolną ramką, padding 16 px, data w nagłówku `static`, stopka `flex-wrap` |
| P0-1 / 08 pkt 20 `html_export.py` padding 34/40, `.edu-dates` 92 px | zrobione | `backend/app/services/cv_generator_b2b/html_export.py:370` | `@media (max-width:600px)`: body 8 px, `.cv` 20/16, `#tiles` 14/16, `.edu` w kolumnie, `.job-head` wrap |
| P0-1 test backendu | zrobione | `backend/tests/test_cv_html_mobile_layout.py` (nowy) | 2 testy, bez bazy (`--noconftest`), zielone |
| P0-1 doklejanie stylu do zamrożonych dokumentów | zrobione | `frontend/src/app/cv/_lib/cv-frame.ts` (nowy), `cv/[token]/page.tsx:157`, `cv/i/[token]/page.tsx:871` | `withMobileCvStyle`: wstawia `<style data-nexus-cv-mobile>` przed `</head>` (albo na początek), pomija, gdy dokument ma już regułę 640/600 px lub znacznik; test `cv-frame.test.ts` |
| P1-1 / 08 pkt 19 `/cv/[token]` ramka `calc(100vh-220px)` — scroll w scrollu | zrobione | `cv/[token]/page.tsx:134-170` | wysokość = treść (`useFitFrameHeight`), zapas `70dvh`, min 400; przyciski wersji językowych `px-3 pt-3 flex-wrap` |
| P2-12 / 08 pkt 20 `/cv/i` wysokość liczona raz | zrobione | `cv/_lib/cv-frame.ts` `useFitFrameHeight`; `cv/i/[token]/page.tsx:673` | pomiar przy `onLoad` + `ResizeObserver` na `body` ramki + `resize`/`orientationchange`; mierzy `body` (nie `documentElement.scrollHeight`, który nie maleje po poszerzeniu) |
| P2-9 `/cv/i` czat — cele dotykowe | zrobione | `cv/i/[token]/page.tsx:640-646` | pole `h-10 md:h-9 min-w-0`, przycisk `h-10 w-10 md:h-9 md:w-9 shrink-0` |
| P2-13 `/cv/i` czat pod całym CV | pominięte | — | funkcja wyłączona flagą `CV_INTERACTIVE_ENABLED=false`; audyt: „naprawa przy włączeniu” (Sheet + pływający przycisk) |
| 08 `/engagement` textarea (zoom iOS) + podwójny padding | zrobione | `engagement/[token]/page.tsx:151-152, 199` | `p-4 pt-8 sm:p-6 sm:pt-12`, karta `p-4 sm:p-6`, textarea `text-base md:text-sm` |
| P2-14 / 08 pkt 18 `/sign` PDF w iframe | zrobione | `sign/[token]/SignForm.tsx:196-217` | < md duży link „Otwórz umowę (PDF)” (do `pdfUrl`), iframe `hidden md:block`, placeholder ładowania `h-24 md:h-[460px]` |
| P1-2 B2B podwójny padding | zrobione | `B2BContractGeneratorV2.tsx:565` | `p-0 md:p-6` (desktop bez zmian) |
| P1-2 B2B zakładki | zrobione | `B2BContractGeneratorV2.tsx:592-604` | `TabsList` `overflow-x-auto`, triggery `shrink-0 whitespace-nowrap` (prymityw `ui/tabs` już przewija < sm — zmiana innego agenta) |
| P1-3 B2B wyszukiwarka `min-w-[18rem]` | zrobione | `B2BContractGeneratorV2.tsx:2208, 2839` | `w-full min-w-0 flex-1 sm:w-auto sm:min-w-[18rem]`; selekty `w-full sm:w-56` / `w-full sm:w-72` |
| P1-4 B2B przyklejona kolumna akcji | zrobione (bez widoku kart — decyzja) | `B2BContractGeneratorV2.tsx:2343, 2576, 2946, 2999` | `md:sticky md:right-0 md:z-10`; ikony `pointer-coarse:h-10 pointer-coarse:w-10` |
| P1-5 B2B stawka progresywna / waluta / data startu | zrobione | `B2BContractGeneratorV2.tsx:4652-4740` | `grid-cols-1 sm:grid-cols-3`, `grid-cols-1 sm:grid-cols-2`, data `flex-col sm:flex-row`, select `w-full sm:w-[150px]` |
| P2-9 B2B filtr daty w nagłówku (18 px) | zrobione | `B2BContractGeneratorV2.tsx:1258` | `hit-area` |
| P2-9 B2B zamknięcie panelu UoP `h-6 w-6` | zrobione | `B2BContractGeneratorV2.tsx:~4890` | `hit-area` (aria-label już był) |
| P2-10 B2B filtry dat `h-8 text-xs` (zoom iOS) | pominięte | — | załatwione globalnie (`globals.css`, pointer-coarse ≥16 px) |
| P2-15 B2B inline edycja klienta `min-w-[16rem]` | zrobione | `B2BContractGeneratorV2.tsx:2399` | `min-w-[12rem] md:min-w-[16rem]` |
| P2-16 B2B podgląd umowy | zrobione | `B2BContractGeneratorV2.tsx:4810, 4832` | nagłówek `flex-wrap gap-2`, iframe `h-[60dvh] min-h-[420px]` |
| P1-6 Historia stawek `overflow-hidden` | zrobione | `contracts/[id]/page.tsx:2269-2300` | `overflow-x-auto`, `min-w-[32rem]`, 1. kolumna `sticky left-0 z-10` |
| P1-7 Dokumenty — akcje ucięte | zrobione | `ContractDocumentsTab.tsx:259-360` | `overflow-x-auto`, `min-w-[36rem]`, 1. kolumna sticky, nazwa pliku `break-words max-w-[14rem] sm:max-w-none`, przyciski `pointer-coarse:p-2.5` + `aria-label` |
| P1-8 Faktury — akcje ucięte | zrobione | `ContractInvoicesTab.tsx:232-300` | `overflow-x-auto`, `min-w-[40rem]`, 1. kolumna sticky, daty/kwoty `nowrap`, przyciski `pointer-coarse:p-2.5` + `aria-label` (kosz dostał też `title`) |
| P1-9 Aneksy — JSON rozpycha kartę | zrobione | `ContractAmendmentsTab.tsx:421, 433` | `min-w-0 flex-1`, siatka `[&>*]:min-w-0` |
| P1-10 Timeline — „Dane techniczne” | zrobione | `contracts/[id]/page.tsx:2343` | `min-w-0 flex-1` |
| P1-11 Analityka — rankingi marży | zrobione | `contracts/analytics/page.tsx:148-235, 531` | tabela w `overflow-x-auto`, `min-w-[34rem]`, kwoty `nowrap`, nazwa `max-w-[12rem] truncate` + `title`; siatka `xl:grid-cols-2` (zamiast `lg:`). Bez sticky: pierwsza kolumna to „#” |
| P1-12 / P1-13 / P2-6 Skrzynka zamówień | poza zakresem | `components/order-mail/OrderMailQueue.tsx` | ten sam plik jest w raporcie 04 (agent klientów/zamówień) — nie edytowałem, żeby nie kolidować |
| P1-14 `ContractsClientPicker` `min-w-[260px]` | zrobione | `ContractsClientPicker.tsx:55-70` | `min-w-0 flex-1 sm:min-w-[260px] sm:flex-none`, nazwa w wewnętrznym `span.truncate`, popover `w-[min(320px,calc(100vw-2rem))]` |
| P1-15 `CandidateRateScheduleFields` 3 pola w wierszu | zrobione | `CandidateRateScheduleFields.tsx:59-120` | `grid grid-cols-1 … sm:grid-cols-[1fr_1fr_1fr_auto]`, < sm etap w ramce; etykiety w każdym wierszu, powtórki `sm:hidden`; kosz `aria-label` |
| (to samo) harmonogramy stawki ramowej i klienta w edycji kontraktu | zrobione | `contracts/[id]/page.tsx:1627, 1812` | ten sam wzorzec co P1-15; przyciski usuwania `h-10 w-10 sm:h-8 sm:w-8` |
| P1-16 Generator CV — wiersz „Wygenerowane CV” | zrobione | `CVGeneratorStandaloneV2.tsx:2122, 2201` | `flex-col … sm:flex-row`, akcje `flex-wrap sm:shrink-0`; ikony dostały `aria-label` (przycisk `size="sm"` ma już `pointer-coarse:min-h-10` w prymitywie) |
| P1-17 Podgląd DOCX — X zasłania „Pobierz” | zrobione | `CVGeneratorStandaloneV2.tsx:2355` | `py-3 pl-4 pr-16`; `h-[92vh]` → `h-[92dvh]` |
| P1-17 dodatek: skalowanie A4 w podglądzie DOCX | pominięte | — | zostaje poziomy scroll w `overflow-auto`; skalowanie `transform` koliduje z `alignB2bLetterheadPreview` — osobna zmiana |
| P1-18 `CVBrandedEditModal` — plakietka pod X | zrobione | `CVBrandedEditModal.tsx:425` (+ banery 384/396/410) | `pl-5 pr-16`; `max-h-[92dvh]` |
| P1-19 Kontraktorzy — podwójny padding | zrobione | `ContractorsListV2.tsx:233` | `md:p-6` (bez paddingu < md; desktop bez zmian) |
| P1-20 Rejestr klienta — daty na sztywno | zrobione | `ClientContractRegister.tsx:569, 578-605, 619` | grupa dat `grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] w-full sm:flex sm:w-auto`, inputy/triggery `w-full sm:w-[…]` |
| P2-1 zakładki kontraktu bez `nowrap` | zrobione | `contracts/[id]/page.tsx:1137` | `shrink-0 whitespace-nowrap` (maski gradientu nie dodawałem) |
| P2-2 / 10-runtime `ContractsListV2` akcje nagłówka | zrobione | `ContractsListV2.tsx:788` | `flex flex-wrap items-center gap-2` |
| P2-3 Benchmark stawki `grid-cols-3` | zrobione | `ContractRateBenchmarkCard.tsx:55` | `grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-4` |
| P2-4 AddProjectDialog 5 kolumn w oknie 672 px | zrobione | `AddProjectDialog.tsx:570` | zostaje `sm:grid-cols-2` (zmiana dotyczy desktopu, taki był zarzut) |
| P2-5 formularze `grid-cols-2` od 0 px | zrobione | `contracts/[id]/page.tsx:1966, 2014`, `ContractAmendmentsTab.tsx:287`, `ContractEquipmentTab.tsx:297`, `CvGeneratedShareModal.tsx:202` | `grid-cols-1 gap-3 sm:grid-cols-2` |
| P2-7 rejestr klienta / kontraktorzy bez kart | zrobione (sticky, bez kart — decyzja) | `ClientContractRegister.tsx:649, 710`, `ContractorsListV2.tsx:309, ~386` | 1. kolumna `max-md:sticky max-md:left-0 max-md:z-10 max-md:bg-card` (desktop bez zmian) |
| P2-8 Kontraktorzy — zakładki | zrobione | `ContractorsListV2.tsx:268-285` | `overflow-x-auto`, przyciski `shrink-0 whitespace-nowrap`; baner draftów `flex-wrap`, tekst `min-w-0` |
| P2-10 iOS zoom globalnie | pominięte | — | zrobione globalnie w `globals.css` (inny agent) |
| P2-11 okna dotykają krawędzi (`ui/dialog`) | poza zakresem | `ui/dialog.tsx` | prymityw — inny agent |
| P2-17 przełączniki w generatorze CV | zrobione | `CVGeneratorStandaloneV2.tsx:1254-1273` | opis `min-w-0 flex-1`, `Switch` `shrink-0` |
| `ContractsBulkActionsBar` `fixed left-1/2` | zrobione | `ContractsBulkActionsBar.tsx:102` | `inset-x-3 mx-auto w-fit` zamiast `left-1/2 -translate-x-1/2` (przy `left:50%` dostępna szerokość to 50vw → pasek łamał się w wąską kolumnę); dół z `safe-area-inset-bottom`; „Wyczyść” `min-h-8` |

## Testy zmienione / dodane
- Dodane: `backend/tests/test_cv_html_mobile_layout.py` (2 testy: blok `@media` w obu szablonach), `frontend/src/app/cv/_lib/cv-frame.test.ts` (4 testy `withMobileCvStyle`).
- Żaden istniejący test nie przypinał zmienionych klas — nic nie zmieniałem w istniejących testach.

## Poza zakresem
- `frontend/src/components/order-mail/OrderMailQueue.tsx` — P1-12 (zakładki bez przewijania), P1-13 (szczegół pod listą < lg → scrollIntoView), P2-6 (nazwa pliku `min-w-0 break-words`, `dl grid-cols-2`, tabela w `overflow-x-auto`). Plik jest w raporcie 04 — do agenta klientów/zamówień.
- `ui/dialog.tsx` (P2-11) — prymityw, inny agent.
- **Publiczne CV bez arkusza stylów** (sanitizer wycina `<head>`/`<style>`) — nie responsywność, ale widoczna wada dla klienta; do decyzji (np. wstrzykiwanie arkusza szablonu we froncie albo dopuszczenie `<style>` z allowlistą w sanitizerze).
- Nie ruszałem `components/cv-rules/**` (inny agent).

## Wyniki sprawdzeń
- `npx eslint` na wszystkich zmienionych plikach frontu: czysto.
- `npx tsc --noEmit -p .`: 1 błąd, nie mój — `.next/types/app/settings/cv-rules/page.ts` (eksport `QUERY_KEY` ze strony `settings/cv-rules`, plik innego agenta / nieaktualne `.next/types`). W moich plikach 0 błędów.
- Backend: `pytest --noconftest tests/test_cv_html_mobile_layout.py` w obrazie `nexus-deps-test:pytest-2026-09-16` (bez bazy, `DEBUG=true`) → **2 passed**. `py_compile` lokalnie niemożliwy (Python 3.9 nie parsuje istniejącego f-stringa w `html_export.py:211` — nie moja zmiana); `ruff` nie ma ani lokalnie, ani w obrazie — **niepotwierdzone**. Sprawdzone w kontenerze: nowy szablon zawiera `@media (max-width: 640px)`, sanitizer wycina `<style>`.
- Vitest (30/27 plików kontraktów, CV, podpisu, B2B): przy obciążeniu maszyny load average 100–560 (inne agenty) każdy przebieg dawał inny zestaw czerwonych testów — wyłącznie timeouty (`Test timed out in 20000ms`, `findByRole` po asynchronicznym wyszukiwaniu nie zdążył w 1000 ms). Pojedynczo: `ContractDocumentsTabPermissions`, `ContractEquipmentTab`, `cv-frame.test.ts`, analityka, `signed-delete-flow`, `B2BContractGeneratorLifecycleTabs` — zielone; `AddProjectDialog` — raz 4, raz 2 różne czerwone (flaky); `ContractRegisterDialog` („Jan Kowalski” po debounce wyszukiwania — plik bez moich zmian), `B2BContractGeneratorStatus` (timeouty 20 s/5 s), `CVGeneratorStandaloneV2` „preselects…” (`aria-checked`, waitFor) — **niepotwierdzone**, do ponownego uruchomienia na nieobciążonej maszynie. Żaden z czerwonych nie wskazuje na zmienione klasy/strukturę.
- Przeglądarka: nieprzeklikane (zakaz `next dev`/`build` w tym zadaniu) — **niepotwierdzone wizualnie**.
