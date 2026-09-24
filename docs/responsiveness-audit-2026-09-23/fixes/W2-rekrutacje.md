# W2-rekrutacje — raport poprawek responsywności

Źródła: `03-jobs-pipeline.md` (całość), `10-runtime.md` (recruitment-v3, FullCandidateSearchStatus, pipeline-v4), `09-pattern-scan.md` (JobChatTab, MarketplaceTable, ProposalPanel). Ścieżki względem `frontend/`.

## Ustalenia

| ustalenie | stan | plik:linia | uwagi |
|---|---|---|---|
| P0-1 Propozycje: panel 372 px obok tabeli | zrobione | `src/components/v2/recruitment/ProposalsSegment.tsx:422`, `ProposalPanel.tsx:116,131` | kontener `flex-col lg:flex-row lg:items-start`, panel `w-full lg:w-[372px] lg:shrink-0`; poniżej `lg` klik w wiersz przewija do panelu (`scrollIntoView` po `matchMedia`) |
| runtime #4 FullCandidateSearchStatus: tekst nachodzi na „Poprzednia” | zrobione | `src/components/talent-radar/FullCandidateSearchStatus.tsx:54,59,97` | `<p>` `flex-[1_1_16rem]` (zamiast `flex-1` z basis 0), paginacja `flex-wrap` w obu wariantach |
| P1-1 Tablica na telefonie 280 px + zagnieżdżony scroll | zrobione | `src/components/v2/pages/KanbanBoardV2.tsx:1581`, `:2546` | poniżej `md` wysokość planszy = `main.clientHeight − 32` (nagłówek przewija się raz, plansza wypełnia ekran); fallback CSS `h-[calc(100dvh-4rem)] md:h-[calc(100dvh-240px)]` |
| P1-2 Dok karty zasłania kolumny 768–1279 | zrobione | `KanbanBoardV2.tsx:2358`, `:2653` | rezerwa `lg:pr-[380px]` (było `xl:`); 768–1023 dok jest nakładką z tłem (`md:block lg:hidden`), klik w tło zamyka |
| P1-3 `/jobs` „Podgląd” poniżej xl ląduje pod listą | zrobione | `src/components/v2/pages/JobsListV2.tsx:1945` + efekt Esc ok. `:988` | poniżej `xl` dok to arkusz z prawej (`fixed … sm:max-w-[420px]`, tło, Esc); od `xl` bez zmian (sticky kolumna) |
| P1-4 Feedback: 3 pola ocen nachodzą | zrobione | `src/components/feedback/InterviewFeedbackModal.tsx:453,571` | `grid-cols-1 sm:grid-cols-3`, przyciski w `grid grid-cols-5` `h-10 w-full` |
| P1-5 MarketplaceTable `overflow-hidden` | zrobione | `src/components/marketplace/MarketplaceTable.tsx:149,152` | `overflow-x-auto` + `min-w-[760px]`. Błąd parsowania z pierwszej wersji (komentarz JSX przed `<div>` w gałęzi `? :`) poprawiony — tsc/eslint czyste |
| P1-6 JobChatTab akcje tylko na hover | zrobione | `src/components/v2/pages/JobChatTab.tsx:720` | `pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 focus-within:opacity-100`, `pointer-coarse:min-h-8` na przyciskach |
| P2-1 iOS zoom (pola) | zrobione globalnie | `globals.css` (inny agent) | nic w plikach zakresu |
| P2-2 `/jobs/new` podwójne marginesy | zrobione | `src/components/v2/jobs/new/NewJobPage.tsx:351`, `NewJobRequestStep.tsx:58,163`, `NewJobReviewForm.tsx:276,460,581` | kontener `md:px-2 md:pt-2`, sekcje `p-4 sm:p-6` |
| P2-3 mail klienta 70vh | zrobione | `NewJobPage.tsx:395` | `max-h-[35dvh] xl:max-h-[70dvh]` |
| P2-4 4 kolumny przy 768, pigułki `h-9` | zrobione | `NewJobReviewForm.tsx:313,343,357` | `md:grid-cols-2 lg:grid-cols-4` + `md:grid-flow-row-dense`; pigułki `min-h-9 leading-tight` |
| P2-5 stopka `/jobs/new` sticky tylko od md | zrobione | `NewJobPage.tsx:450` | `sticky bottom-0` wszędzie, `[@media(max-height:600px)]:static` |
| P2-6 EditJobModal siatki | pominięte | `src/components/AppShell.tsx:1312,1330` | poza zakresem |
| P2-7 AIJobWriterModal | zrobione | `src/components/v2/jobs/AIJobWriterModal.tsx:66-84` | `grid-cols-1 sm:grid-cols-2`, `items-start` + `my-auto` (wysokie okno nie traci góry), padding `p-4 sm:p-6`, `hit-area` na „Zamknij” |
| P2-8 QuestionBankTab | zrobione | `src/components/prep/QuestionBankTab.tsx:368` | `grid-cols-1 sm:grid-cols-2` |
| P2-9 kosz na karcie niewidoczny na dotyku | zrobione | `KanbanBoardV2.tsx:1072` | `pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100` |
| P2-10 scroll-snap planszy | zrobione | `KanbanBoardV2.tsx:2546`, kolumny `snap-start` (`:1210`, kolumna „Nowi”) | `pointer-coarse:snap-x pointer-coarse:snap-proximity` — proximity, by nie walczyć z auto-scrollem DnD; mysz bez zmian |
| P2-11 małe cele dotyku | zrobione | checkbox `KanbanBoardV2.tsx:835` (`pointer-coarse:after:-inset-2`), Screening `:1097`, `PipelineFiltersRail.tsx:51,146,159,207,223`, `BoardReviewSection.tsx:149-165`, `PipelineCandidateDock.tsx:618,630,643`, `JobReadinessDock.tsx:900,912,926`, `JobsListV2.tsx:666,686,1780,1794,1966` | wszystko `pointer-coarse:` — desktop bez zmian |
| P2-12 dok przy pasku „podglądaj jako” | zrobione | `KanbanBoardV2.tsx:2655` (+ stan `chromeTop`) | top doku mierzony z `main#main.getBoundingClientRect().top`, bez zmian w powłoce |
| P2-13 PersonPanel wiersz etapu | zrobione | `src/components/v2/recruitment/PersonPanel.tsx:756` | `flex-wrap`, select `min-w-[10rem] flex-1 pointer-coarse:h-10` |
| P2-14 DlReviewPanel stopka | zrobione | `src/components/v2/recruitment/DlReviewPanel.tsx:503` | `max-h-[50dvh] overflow-y-auto` |
| P2-15 czat `h-[70vh]` | zrobione | `JobChatTab.tsx:350,365,385` | `h-[70dvh]` |
| P2-16 nagłówek rekrutacji ucina tytuł | zrobione | `src/components/v2/jobs/JobDetailCompactHeader.tsx:257,268` | tytuł `max-sm:line-clamp-2 sm:truncate`, klient `max-sm:hidden` |
| P2-17 KPI 9,5 px | zrobione (inny agent) | `JobDetailCompactHeader.tsx:169` | już `text-[10px]`, na dotyku 11 px z globals |
| P2-18 tabela `/jobs` na telefonie | zrobione | `JobsListV2.tsx:~515,564` | przyklejona 1. kolumna „Rekrutacja” poniżej `md` (`max-md:sticky left-0 bg-card w-[200px]`), zgodnie z decyzją „scroll + sticky, bez nowych kart”; kafelków nie wymuszam |
| P2-19 3 kolumny przy xl (filtry rozwinięte + dok) | zrobione | `JobsListV2.tsx:159`, aside filtrów ok. `:1150` | 3 kolumny od `2xl`; na `xl` otwarty dok zastępuje filtry |
| P2-20 Champion: „Zapisz” tylko na górze | zrobione | `src/components/ChampionProfileEditor.tsx:362` | nagłówek z „Zapisz” `sticky top-0` poniżej `xl`; opis `hidden sm:block` (żeby przyklejony pasek był niski na telefonie) |
| P2-21 `divide-x` w 1 kolumnie | zrobione | `src/components/ChampionProfileSuggestionReview.tsx:412` | `divide-y md:divide-y-0 md:divide-x` |
| P2-22 Prep kit | zrobione | `src/app/jobs/[id]/prep/[candidateId]/page.tsx:101,113-139` | `md:p-6`, nagłówek `flex-col sm:flex-row`, h1 `text-xl sm:text-2xl` |
| P2-23 `/sourcing/marketplace` `<main>` + ContractorMatchCard + PostingsSection | zrobione | `src/app/sourcing/marketplace/page.tsx:38`, `src/components/sourcing/ContractorMatchCard.tsx:242-266`, `src/components/v2/recruitment/PostingsSection.tsx:98` | `<div className="mx-auto max-w-7xl">`; wiersz dopasowania `flex-wrap`; okno publikacji `max-h-[90dvh] overflow-y-auto` |
| Uwaga: `ui/dialog.tsx` margines | pominięte | — | poza zakresem (prymitywy) |
| 09: `100vh` w plikach zakresu | zrobione | `src/app/jobs/layout.tsx:21`, `JobReadinessDock.tsx:883`, `workbench-chrome.tsx:455`, harnessy `preview/{pipeline-v4,new-job,recruiter,jobs-list-v3}` | → `dvh` / `min-h-dvh` |
| Niepotwierdzone: `max-w-[320px]` na `<td>`, DnD na dotyku, ChampionIntake `max-h-[90vh]` | pominięte | — | wymagają przeglądarki; ChampionIntake nietknięty |

## Zmienione testy
Brak — żaden test nie przypinał zmienionych klas.

## Poza zakresem
- `src/components/AppShell.tsx:1312,1330` (EditJobModal `grid-cols-2/3` bez breakpointu) — P2-6.
- `src/components/ui/dialog.tsx:59` — margines boczny okien na telefonie.
- Opcjonalnie powłoka: zmienna CSS wysokości chrome — niepotrzebna, dok mierzy `main#main`.

## Wyniki sprawdzeń
- `npx tsc --noEmit -p .` — 0 błędów w `src/`; jedyne błędy to nieaktualne `.next/types` (`settings/cv-rules/page.ts`, znany artefakt, niezwiązany).
- `npx eslint <32 pliki>` — 0 błędów (ostrzeżenia `no-explicit-any` / `no-img-element` sprzed zmian).
- `npx vitest run` (recruitment, jobs, feedback, marketplace, talent-radar, KanbanBoardV2, JobsListV2, jobs/new; 567 testów) przy load average 180–950: wszystkie padnięcia to timeouty `findBy*` (różne testy w kolejnych biegach). Ponowny bieg padniętych plików: MarketplaceTable, TalentRadarWorkspaceSkills, ChampionSectionNav, JobReadinessDock, PanelSavedViews, ProposalPanel, ProposalsSegment, RequestRequirementsRail, KanbanBoardV2, NewJobPage — zielone. `ScreeningReassignSuggestions.test.tsx` nadal pada na `findByText` w stanie przeciążenia — testuje `ScreeningReassignSuggestions`/`ScreeningForm`, których nie dotykałem; **niepotwierdzone**, czy pada też bez obciążenia.
