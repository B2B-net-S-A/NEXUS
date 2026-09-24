# Pomiar responsywności w przeglądarce (runtime) — NEXUS frontend

Data: 23.09.2026 · worktree `app-responsiveness-audit-cb0a5f` (HEAD `5f7d89d1f`) · Chromium headless (Playwright 1.63)

## Jak mierzono

- **Serwer: produkcyjny build (`next build --no-lint` + `next start`), nie `next dev`.** Dev na tej maszynie był nieużywalny: load average 43–350 na 8 rdzeniach (inne sesje, VM), kompilacja trasy 150–250 s, render 40–180 s, timeouty 240 s. Build nie zmienia żadnego pliku śledzonego (`git status` czysty), `NEXT_PUBLIC_API_URL=http://127.0.0.1:9` — zero ruchu do backendu.
- **URL-e:** 40 harnessów `/preview/*` (+ warianty `candidate-profile?tab=recruitments|activity|documents`, `candidates-list?dialog=1`, `new-job?state=request|gaps`, `calendar-cycle?as=dl`, `pipeline-v4?as=dl`) oraz `/login`, `/register`, `/kariera`, `/kariera/rodo`. Pominięte: `/preview/cortex`, `/preview/ds-kit` (307 → `/login`).
- **Szerokości:** 360, 390, 768, 1024, 1280, 1440, 1920 × wysokość 800; poniżej 768 `isMobile` + `hasTouch`. Po `networkidle` + 1,5 s.
- **Przelew strony:** `max(scrollWidth, innerWidth) − szerokość nominalna`. Ważne: w emulacji mobilnej Chrome **poszerza layout viewport do szerokości treści** (strona się oddala), więc `innerWidth` rośnie razem z przelewem i naiwny test `scrollWidth > innerWidth` daje 0. Dlatego porównanie jest z szerokością urządzenia.
- **Winowajcy:** elementy wychodzące poza szerokość, które nie siedzą w kontenerze `overflow-x: auto/scroll` (z uwzględnieniem bloku zawierającego — element `absolute` ucieka z `overflow` nieustawionego przodka). Osobno liczony „**ukryty przelew**": treść wychodząca poza ekran, ale ucięta przez `overflow: hidden` w kontenerze szerokim na ≥90% ekranu — nie daje poziomego scrolla, tylko **znika** (nieosiągalne przyciski/kolumny).
- Tap targety (<32×32 px) i tekst <11 px liczone przy 390.
- Surowe dane: `runtime/results-final.json` (mobile) + `runtime/results.json` (≥768), skrypty `runtime/measure.mjs`, `runtime/probe*.mjs`, zrzuty `runtime/shots/*__{390,768,1280}.png` (156 plików).

## Wyniki — przelew strony w px (0 = brak)

Tylko trasy z jakimkolwiek przelewem; pozostałe 42 URL-e × 7 szerokości = **0 px**.

| URL | 360 | 390 | 768 | 1024 | 1280 | 1440 | 1920 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `/preview/order-tile` | **457** | **427** | **49** | 0 | 0 | 0 | 0 |
| `/preview/order-mail` | **90** | **59** | 0 | 0 | 0 | 0 | 0 |
| `/preview/my-people` *(artefakt harnessu)* | 84 | 54 | 0 | 0 | 0 | 0 | 0 |
| `/preview/recruitment-v3` | **45** | **15** | 0 | 0 | 0 | 0 | 0 |
| `/preview/ezdrowie-contract-structure` | **39** | **9** | 0 | 0 | 0 | 0 | 0 |
| `/preview/contracts-consolidation` (renderuje `/contracts`) | **9** | 0 | 0 | 0 | 0 | 0 | 0 |
| `/preview/candidates` | 0 | 0 | 0 | **271** | **15** | 0 | 0 |

„Ukryty przelew" (treść ucięta, bez scrolla):

| URL | 360 | 390 | 768 | 1024 | ≥1280 |
|---|---:|---:|---:|---:|---:|
| `/preview/candidates-list` (+`?dialog=1`) | 113 el. | 113 el. | 60 el. | 12 el. | 0 |
| `/preview/career-share` | 10 el. (+82 px) | 10 el. (+52 px) | 0 | 0 | 0 |
| `/preview/candidate-profile?tab=documents` | 4 el. (+12 px) | 0 | 0 | 0 | 0 |

Trasy publiczne (`/login`, `/register`, `/kariera`, `/kariera/rodo`) — 0 px na każdej szerokości, ale bez backendu renderują się w stanie zdegradowanym (`/register` bez formularza, `/login` 1 element interaktywny, `/kariera` ~500 znaków), więc to słaby dowód dla ich pełnej wersji.

## Winowajcy (potwierdzone zrzutem lub sondą)

### 1. Kafelek kontraktora — pasek akcji wychodzi z karty (poważne)
- `src/components/OrdersAndContractsTab.tsx:1379` — `<div className="flex flex-wrap items-center gap-1.5 shrink-0">` wewnątrz `flex … flex-wrap` (l. 1098).
- Pasek ma 772 px szerokości przy każdej szerokości ekranu <1024: po zawinięciu do własnej linii `shrink-0` + `flex-basis: auto` = szerokość max-content, więc wewnętrzne `flex-wrap` nigdy się nie włącza. Przyciski „Zakończ zamówienie / Usuń zamówienie / Zakończ współpracę" leżą poza kartą.
- Zrzut `shots/preview_order-tile__390.png`: karta ma ~325 px, przyciski ciągną się do 817 px; na telefonie cała strona jest oddalona ×2. Przy 768: +49 px. To jest widok „Zamówienia" profilu klienta — realny ekran, nie tylko harness.

### 2. Lista kandydatów — kolumna „Przypisz" ucięta poniżej ~1100 px (poważne, niewidoczne w liczniku przelewu)
- `src/lib/candidate-table-columns.ts:84` — `minWidth: 32 + Σ minWidth kolumn` pomija `gap-3` (8 × 12 px) i `px-4` (32 px) siatki wiersza.
- `src/components/v2/pages/CandidatesListV2.tsx:1634-1640` — kontener `candidate-list-scroll` dostaje ten zaniżony `minWidth` (910 px) i ma `overflow-x-hidden`; siatka wiersza ma 1022 px. Zewnętrzny `overflow-x-auto` przewija tylko do 910 px.
- Skutek: przy 360–1024 px ostatnie ~112 px wiersza (przycisk „Przypisz", część „CV") są **nieosiągalne** — ani widoczne, ani przewijalne. Sonda przy 390: przycisk „Przypisz" na `right=1041`, kontener kończy się na 910. Przy 1024: ucięte 24 px.
- Dodatkowo na 390 (`shots/preview_candidates-list__390.png`): stopka paginacji łamie „1–50 z" w trzech liniach, a „Następna" jest ucięta (`CandidatesListV2.tsx` ok. l. 1908, `flex items-center gap-2` bez `flex-wrap`).

### 3. Tabela „Czytelna lista kandydatów" — `sr-only` rozpycha stronę na desktopie
- `src/components/candidates/preview/CandidateListPreview.tsx:73-83` — `<span className="sr-only">Akcje</span>` (position:absolute) w tabeli `min-w-[1100px]` wewnątrz `overflow-x-auto`, bez `relative` na kontenerze. Absolutny element ucieka z przewijanego kontenera i poszerza dokument: **+271 px przy 1024, +15 px przy 1280** (poziomy scroll całej strony). Naprawa: `relative` na `div.overflow-x-auto`. Komponent to harness/preview, ale ten sam wzorzec (sr-only w tabeli przewijanej bez `relative`) warto sprawdzić w realnych tabelach.

### 4. „Do przejrzenia" (propozycje) — panel osoby o stałej szerokości
- `src/components/v2/recruitment/ProposalPanel.tsx:116,131` — `w-[372px] shrink-0`, obok listy `min-w-0 flex-1` w `ProposalsSegment.tsx:416` (`flex … gap-4`, bez przejścia na kolumnę).
- Przy 360/390 panel wystaje o 45/15 px, a lista propozycji **zapada się do zera** (na zrzucie `shots/preview_recruitment-v3__390.png` z listy zostaje sama pionowa linia). Dla porównania `PersonPanel.tsx:889` robi to dobrze: `w-full … lg:w-[372px]`.
- Ten sam zrzut: w `src/components/talent-radar/FullCandidateSearchStatus.tsx:53-55` `<p className="min-w-0 flex-1">` w wierszu `flex-wrap` ma `flex-basis: 0`, więc paginacja nigdy nie spada do nowej linii — tekst „Przegląd zakończony: 52 widocznych z 58400 sprawdzonych" łamie się po jednym słowie i **nachodzi na przycisk „Poprzednia"**.

### 5. Skrzynka zamówień z maila — zakładki bez zawijania
- `src/components/order-mail/OrderMailQueue.tsx:405` — `<div className="mt-4 flex gap-2" role="tablist">` bez `flex-wrap`/`overflow-x-auto`; ostatnia zakładka „Nierozpoznane" wychodzi o 89/59 px przy 360/390, a lista dokumentów (`ul[data-testid=order-mail-list]`, 383 px) o kolejne ~23 px.

### 6. Struktura umów CeZ — chip umowy wykonawczej
- `src/components/client-profile/ContractStructureSection.tsx:180` — `inline-flex … rounded-full` z numerem, statusem „ZAKOŃCZONA", licznikiem i ołówkiem; 320 px, nie zawija się: +39 px (360), +9 px (390).

### 7. Rejestr kontraktów — przyciski nagłówka
- `src/components/v2/pages/ContractsListV2.tsx:788` — `flex items-center gap-2` („Analityka / Eksport / Nowy kontrakt", 345 px) bez zawijania: +9 px przy 360. (Harness `contracts-consolidation` przestawia adres na `/contracts` i renderuje prawdziwy `ContractsListV2`.)

### 8. „Udostępnij rekrutację" — zakładka „Mój link ogólny" szersza niż okno
- `src/components/v2/career-share/GeneralLinkTab.tsx:197` — `grid gap-6 lg:grid-cols-[…]`: poniżej `lg` siatka ma niejawny tor `auto`, który przyjmuje min-content dzieci (377 px) zamiast szerokości okna. `DialogBody` ma `overflow: hidden`, więc zamiast scrolla treść jest ucięta: pole adresu, trzeci kafel statystyk (`grid-cols-3`, l. 310) i podgląd posta LinkedIn obcięte z prawej (`shots/preview_career-share__390.png`). Naprawa: `grid-cols-1` / `grid-cols-[minmax(0,1fr)]` jako baza.

### 9. Profil kandydata → Pliki — pasek akcji wiersza
- `src/components/v2/files/CandidateFilesTab.tsx:301` — `flex items-center gap-3 shrink-0` (select rodzaju + Podgląd + Pobierz) ucięte o 12 px przy 360 przez `overflow-hidden` karty.

### Artefakt harnessu (nie błąd produktu)
- `/preview/my-people`: ramka `w-[420px] shrink-0` w `src/app/preview/my-people/page.tsx:97`. Prawdziwy panel (`MyPeoplePanel.tsx:247`) ma `w-full max-w-[420px]`.

## Tap targety i drobny tekst (390 px, 47 stron z treścią)

- **1325 elementów interaktywnych, z czego 776 (58,6%) ma bok <32 px.** Wśród pierwszych przykładów z każdej strony ok. 100 ma bok <24 px.
- Najgorsze strony (małe / wszystkie): `order-lifecycle` 123/131, `order-md-scopes` 79/81, `order-new-from-pdf` 67/74, `pipeline-v4` 57/75, `order-tile` 43/43, `recruitment-v3` 35/42, `candidates-list` 34/52, `champion-profile` 34/68, `dl-alerts` 25/28.
- Typowe wzorce (najmniejsze):
  - ołówki edycji w miejscu **12×12** — `src/components/orders/InlineOrderFields.tsx` (`text-muted-foreground/50 hover:text-violet-600`), `order-tile`, `contract-candidate-contact`;
  - „Usuń filtr" w chipach **16×16** (`inline-flex size-4 … rounded-full`), checkboxy **16×16** (`peer h-4 w-4 … rounded-md`), ołówek umowy wykonawczej **16×16** (`-mr-1 rounded-full p-0.5`), usuwanie tagu „Usuń Java 17+" **14×14** (`new-job`);
  - ikony akcji linii zamówienia **28×28** (`rounded-md p-1.5`), pastylki filtrów `h-7` (28 px) w `jobs-list-v3`, `recruitment-v3`, `pipeline-v4`; nawigacja w podglądzie CV **22–25 px**;
  - linki tekstowe wysokości 14–20 px (nazwiska na kartach, „Edytuj", „Zmień").
- **Tekst <11 px: 655 węzłów.** Najwięcej: `pipeline-v4` 121–122 (m.in. 9,5 px „SLA: —"), `champion-profile` 77 (etykiety `text-[10px] uppercase`), `order-md-scopes` 68, `contracts-consolidation` 57, `order-lifecycle` 31, `jobs-list-v3` 30 (nagłówki tabeli `text-[10px]`). Główne źródło: `Badge` w rozmiarze 10 px i etykiety `text-[10px]`. `cv-search` ma 6,4 px — to render PDF (pdf.js) w skali, nie UI.

## Czego ten pomiar nie pokrywa

- Ekrany za logowaniem (pełny shell z paskiem bocznym, `/dashboard`, `/jobs/[id]`, `/candidates/[id]`) — widać tylko ich fragmenty w harnessach. `/preview/shell`, `/preview/table`, `/preview/tokens`, `/preview/recruiter` przekierowują na `/login` (brak w publicznych ścieżkach middleware) — niezmierzone.
- Strony publiczne bez backendu renderują stan awaryjny.
- Tablica Pipeline v4 i tabele z `overflow-x-auto` przewijają się poziomo zgodnie z zamysłem — nie liczone jako błąd. Harness `pipeline-v4` pokazuje w kolumnie „Nowi" błąd „Nie wczytano listy do przejrzenia" (niezasiane zapytanie propozycji) — poza zakresem tego pomiaru.

## Zrzuty do obejrzenia

- `runtime/shots/preview_order-tile__390.png` — pasek akcji poza kartą (strona 817 px).
- `runtime/shots/preview_candidates-list__390.png` — ucięta paginacja; kolumny za „Ostatnie stanowisko" niedostępne.
- `runtime/shots/preview_recruitment-v3__390.png` — zapadnięta lista + nachodzący tekst statusu przeglądu.
- `runtime/shots/preview_career-share__390.png` — ucięta zakładka „Mój link ogólny".
- `runtime/shots/preview_my-people__390.png`, `preview_order-mail__390.png`, `preview_ezdrowie-contract-structure__390.png` — przelewy mobilne.
- `runtime/shots/preview_candidates__1280.png` — pusty pas z prawej od `sr-only` (przy 1024 +271 px; zrzutu 1024 nie robiono).
