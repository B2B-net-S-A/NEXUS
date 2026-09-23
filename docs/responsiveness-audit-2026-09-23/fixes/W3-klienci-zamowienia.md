# W3 — Klienci + Zamówienia: raport poprawek responsywności

Źródła: `04-clients-orders.md` (całość), `10-runtime.md` (order-tile, order-mail, ezdrowie-contract-structure, cele dotykowe order-lifecycle / order-md-scopes / order-new-from-pdf, ołówki `InlineOrderFields`), `09-pattern-scan.md` (DlClientsTable, tabela OrderMailQueue).
Ścieżki względem `frontend/`. Po przerwie na limit API żadnej zmiany nie robiłem od nowa ani nie cofałem — ołówki `InlineOrderFields` były już zrobione przed przerwą.

## Ustalenia

| Ustalenie | Stan | plik:linia | Uwagi |
|---|---|---|---|
| Runtime #1: pasek akcji kontraktora ma 772 px (+427 px przy 390) | zrobione | `components/OrdersAndContractsTab.tsx:1384` | `shrink-0` → `min-w-0 max-w-full`. O łamaniu linii dalej decyduje max-content, więc desktop się nie zmienia, a na telefonie wewnętrzny `flex-wrap` wreszcie działa. Poprawiony komentarz przy `basis-80`. |
| P2-9/P2-19: przyciski akcji kontraktora ~26 px | zrobione | `OrdersAndContractsTab.tsx:652, 1393+` | `pointer-coarse:min-h-10` na 5 przyciskach tekstowych, w tym `CompleteOrderButton`. Kosze `:1613/:1748` → `hit-area`. Select umowy wykonawczej `:1226` → `pointer-coarse:py-1.5`. Menu „⋯” pominięte: pasek się zawija, a cele są już 40 px. |
| P1-1 nagłówek profilu, akcje bez zawijania | zrobione | `app/clients/[id]/page.tsx:967` | `flex-wrap`; `p-4 sm:p-6`; ikona firmy `hidden sm:flex`; tytuł `break-words`; „Edytuj”/„Usuń klienta” `pointer-coarse:min-h-10`; link www `break-all` |
| P1-2 lista klientów, przyciski nagłówka | zrobione | `v2/pages/ClientsListV2.tsx:498` | `flex flex-wrap` |
| P1-3 kafel MRR, kwota wychodzi poza kafel | zrobione | `client-profile/SummaryBar.tsx:45`, `StatsCard.tsx:101` | `grid-cols-1 min-[420px]:grid-cols-2`; wartość `text-lg sm:text-xl break-words` |
| P1-4 AnalyticsTab | pominięte | — | Plik należy do innego agenta (poza moim zakresem) |
| P1-5 ProjectsTab, akcje zjadają tytuł | zrobione | `app/clients/[id]/ProjectsTab.tsx:83–103` | wiersz `flex-wrap`, link `basis-48`, akcje `w-full sm:w-auto sm:shrink-0`; ikona linku `hit-area` |
| P1-6 OwnersTab, długie e-maile | zrobione | `app/clients/[id]/OwnersTab.tsx:250, 379` | `flex-wrap` + `min-w-0 flex-1`, e-mail `break-all`, wiersz nazwiska `flex-wrap`, kosze `hit-area` + `aria-label`, przyciski `pointer-coarse:min-h-10` |
| P1-7 RateCardsTab, `overflow-hidden` ucina tabelę | zrobione | `components/RateCardsTab.tsx:406–421` | `overflow-x-auto`, `min-w-[640px]`, przyklejona kolumna „Rola”, kwoty i daty `whitespace-nowrap`, ikony `pointer-coarse:p-2.5` |
| P1-8 umowy ramowe, wiersz metadanych | zrobione | `FrameworkContractsTab.tsx:282–305` | `flex-wrap gap-x-4 gap-y-1`; nazwa pliku `truncate` + `title`; kosze `hit-area` |
| P1-9 formularze umowy ramowej i aneksu bez przewijania | zrobione | `FrameworkContractsTab.tsx:494, 648` | Formularz `flex max-h-[90dvh] flex-col`, pola w przewijanym body, stopka `shrink-0` (zawsze widoczna) |
| P1-10 trzy modale MaterialsTab | zrobione | `app/clients/[id]/MaterialsTab.tsx:405, 941, 1074` | `flex max-h-[90dvh] flex-col`; body `min-h-0 flex-1 overflow-y-auto`; stopka `shrink-0` (lista szablonów `flex-wrap`); zamknięcie `hit-area` + `aria-label` |
| P1-11 ModalShell (3 okna akcji) | zrobione | `client-profile/actions/CloseJobAsLostModal.tsx:106–120` | Wariant lekki: `p-4` na tle, panel `max-h-[90dvh] overflow-y-auto`, X z `hit-area` + `aria-label`. Bez migracji na AppModal, bo okna mają przyciski wewnątrz `children` (stopki nie da się oddzielić bez zmiany 3 konsumentów). |
| P1-12 / runtime #5: zakładki skrzynki zamówień | zrobione | `order-mail/OrderMailQueue.tsx:418` | `flex-wrap` |
| P1-13 szczegóły pod listą poniżej `lg` | zrobione | `OrderMailQueue.tsx:378–391, 443` | Po kliknięciu pozycji `scrollIntoView` do `[data-testid=order-mail-detail]`, tylko przy `max-width:1023px`. Bazowy tor siatki `grid-cols-[minmax(0,1fr)]` (lista 383 px rozpychała stronę). Nazwa klienta `min-w-0`, data `shrink-0`. |
| P1-14 usuwanie wpisu wiedzy tylko po najechaniu | zrobione | `app/clients/[id]/page.tsx:348` | `pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 pointer-fine:group-focus-within:opacity-100 focus-visible:opacity-100` + `hit-area` |
| P2-1 tabela konsultantów | zrobione | `client-profile/ConsultantsTable.tsx:78–98` | `min-w-[720px]`, kolumna „Konsultant” przyklejona (`bg-card dark:bg-muted` = tło karty profilu), kwoty i daty `whitespace-nowrap` |
| P2-2 lista klientów bez przyklejonej kolumny | zrobione | `ClientsListV2.tsx:699, 865` | `sticky left-0` na „Firma” (th: `bg-background`, td: `bg-card`). Podświetlenie wiersza po najechaniu zachowane gradientem `[tr:hover_&]` — desktop bez zmian. |
| P2-3 kafle kategorii zajmują ~330 px wysokości | zrobione | `ClientsListV2.tsx:~640–670` | Poniżej `sm`: `p-3`, bez `min-h-24`, ikona 36 px, opis `hidden sm:block`. Jedna kolumna zostaje (w trzech kolumnach tytuł i licznik by się nie zmieściły). |
| P2-4 treść dostępna tylko w tooltipie (`title`) | częściowo | `StatsCard.tsx:105–107` | Podpis kafla widoczny na dotyku (`pointer-fine:sr-only`). Tooltipy Radix w `ClientsListV2` (Status klienta, liczniki, „ręcznie”) pominięte — potrzebny wspólny wzorzec toggletip w `ui/tooltip`; to prymityw innego agenta. |
| P2-5 pasek zakładek nie przewija się do aktywnej | zrobione | `app/clients/[id]/page.tsx:876–890, ~1030` | `ref` na aktywnej zakładce; efekt przewija sam pasek w poziomie przez `scrollLeft`, nie `scrollIntoView` — strona nie podskakuje. `px-3 sm:px-6`. Maskę-gradient pominąłem. |
| P2-6 padding karty profilu | zrobione | `page.tsx:950, ~1060` | `p-4 sm:p-6` (nagłówek i treść zakładki) |
| P2-7 formularze 2-kolumnowe | zrobione | `page.tsx:279, 401, 421, 440`; `EditOrderDialog.tsx:564, 590, 615, 641`; `ExtendOrderDialog.tsx:356, 395`; `NewContractorOrderDialog.tsx:722, 752, 783`; `FrameworkContractsTab.tsx:506, 533`; `MaterialsTab.tsx` (wymóg); `OrderMailQueue.tsx` `<dl>` | `grid-cols-1 sm:grid-cols-2`; checkbox „Wymagany” `sm:mt-6` |
| P2-8 zoom iOS | pominięte | — | Załatwione globalnie w `globals.css` (reguła pointer-coarse) |
| P2-9 cele dotykowe | zrobione | `OrderGroupCard.tsx` (8× ikony, 6× przyciski), `OrderPlanLineCard.tsx:244` + przyciski, `OrderGroupFormModal.tsx:627/645/664`, `LineMonthlyHistoryDialog.tsx:293/302`, `page.tsx` serce/ołówek/kosz kontaktu (`hit-area` + `pointer-coarse:gap-4`), linki mail/telefon (`pointer-coarse:min-h-10`), `MaterialsTab.tsx:307/857/865`, `KeyRelationshipsPanel.tsx` | Ikony: `hit-area` albo `pointer-coarse:p-2.5`; przyciski tekstowe: `pointer-coarse:min-h-10` / `py-2(.5)` |
| Runtime: ołówki `InlineOrderFields` 12×12 | zrobione | `orders/InlineOrderFields.tsx:92, 214` (+ ✓/✕ `:131, 141, 287, 297`) | Ołówki `hit-area`. ✓/✕ stoją obok siebie, więc dostały `pointer-coarse:p-2` zamiast `hit-area` (nakładające się pola trafienia zamieniałyby potwierdzenie w anulowanie). |
| P2-10 OrderPlanLineCard, breakpoint wiewportu w modalu | zrobione | `client-profile/orders/OrderPlanLineCard.tsx:208, 254` | Karta `@container`; kafle `@lg:grid-cols-2 @2xl:grid-cols-4` |
| P2-11 filtry zamówień, daty ~106 px przy 1280 | zrobione | `client-profile/orders/OrderListControls.tsx:92` | `xl:` → `2xl:grid-cols-4`, pola dat `min-w-0` |
| P2-12 wcięcie notatki relacji | zrobione | `page.tsx` (notatka relacji) | `ml-0 sm:ml-12 pl-3`, bez martwego `pl-12` |
| P2-13 długie e-maile kontaktów | zrobione | `page.tsx:676`, `clients/KeyRelationshipsPanel.tsx:176` | `<span class="break-all">`, ikona `shrink-0` |
| P2-14 / 09-scan: tabela w szczegółach maila | zrobione | `OrderMailQueue.tsx:696–747` | Owinięta w `overflow-x-auto`, tabela `min-w-[520px]` |
| P2-15 surowe modale `90vh` | zrobione | `NewContractorOrderDialog.tsx:~460`, `ExtendOrderDialog.tsx:294`, `KeyRelationshipDialog.tsx:81` | `flex max-h-[90dvh] flex-col`, przewijane body, stopka `shrink-0` zawsze widoczna. Bez migracji na AppModal (duża zmiana z ryzykiem dla testów). |
| P2-16 dokumenty w karcie klienta (playbook) | zrobione | `client-playbook/ClientPlaybookForm.tsx:289, 298, 303` | `w-full sm:w-56`, `w-full min-w-0 sm:w-auto sm:min-w-64`, „usuń” `pointer-coarse:min-h-10` |
| P2-17 przycisk czyszczenia wyszukiwarki 28 px | zrobione | `ClientsListV2.tsx:604` | `pointer-coarse:h-9 w-9`. Nie `hit-area`, bo `hit-area` nadpisuje `position:absolute`. |
| P2-18 nagłówek karty zamówienia | zrobione | `client-profile/orders/OrderGroupCard.tsx:1169–1236, 1250` | `px-4 sm:px-5`; poniżej `sm` 3 awatary (`max-sm:hidden`) i własny licznik „+N” |
| Runtime #6: chip umowy wykonawczej CeZ (+39 px) | zrobione | `client-profile/ContractStructureSection.tsx:180–215` | Chip `max-w-full flex-wrap`, numer `break-all`, ołówek `hit-area`; nagłówek części `flex-wrap min-w-0` |
| 09-scan: `DlClientsTable` w `overflow-hidden` | zrobione | `app/dashboard/delivery-lead/_components/DlClientsTable.tsx:26–49` | Wewnętrzny `overflow-x-auto`, `min-w-[480px]`, przyklejona kolumna DL, `w-36 sm:w-48` |
| Nagłówek MultiConsultantOrdersTab | zrobione | `client-profile/orders/MultiConsultantOrdersTab.tsx:1009` | Prawa grupa `flex-wrap` |
| Tabela `RateHistoryWidget` bez wrappera (z przeglądu zakresu) | zrobione | `RateHistoryWidget.tsx:196` | Owinięta w `overflow-x-auto` |
| Harnessy `min-h-screen` | zrobione | `app/preview/order-tile/page.tsx:192`, `app/preview/inactive-clients-cleanup/page.tsx:182` | `min-h-dvh`, `p-4 sm:p-*` |

## Zmienione testy
Brak. Żaden test w zakresie nie przypinał zmienionych klas.

## Poza zakresem
- `src/components/AnalyticsTab.tsx:104, 179` (P1-4) — inny agent.
- `src/components/ui/tooltip.tsx` — tooltipy nie otwierają się dotykiem (P2-4: `ClientsListV2` Status klienta, liczniki, „ręcznie”). Potrzebny wspólny toggletip albo Popover.
- `src/components/ui/dialog.tsx` — marginesy i `90vh` (uwaga przekrojowa w 04).
- `src/__tests__/responsive-guards.test.ts` pada na plikach spoza mojego zakresu: `h-screen` w shellu i `app/profile/page.tsx:308` (akcja tylko po najechaniu).
- `ContractsListV2.tsx:788` (runtime #7) — należy do agenta od kontraktów.

## Wyniki sprawdzeń
- **eslint** (31 moich plików): 0 błędów, 4 ostrzeżenia `no-explicit-any` w `OwnersTab.tsx:64/76/94/113` — istniały wcześniej, nie z tej zmiany.
- **tsc --noEmit**: jedyny błąd to `.next/types/app/settings/cv-rules/page.ts` (nieaktualne typy `.next`, strona spoza zakresu). W plikach `src` błędów nie ma.
- **vitest**: pomiar niepewny, bo maszyna była mocno przeciążona (load average 280–320 na 8 rdzeniach, pojedyncze testy trwały 5–14 s).
  - Pełny zakres (37 plików, `--maxWorkers=3`): 372/396 zielonych. Czerwone to timeouty i `findBy` (domyślne 1000 ms) plus 2 z `responsive-guards` (pliki innych agentów).
  - Ponowny bieg szeregowy 4 podejrzanych plików (`ClientsListV2Debounce`, `OrderMailQueueView`, `NewContractorOrderDialog`, `OrdersAndContractsTab`): 125/127. Czerwone zostały 2 testy, oba pierwsze `findBy*` w pliku.
  - Kontrola: w trzecim biegu padają w ten sam sposób także testy plików, których nie ruszałem (`ConsultantLineModal.tsx`, `ClientPlaybookCard.tsx` — `git diff` pusty). Czerwone wyniki wynikają więc z obciążenia, nie ze zmian. Test „domyślnie pobiera aktywnych” w `ClientsListV2` w trzecim biegu przeszedł.
  - Do potwierdzenia na nieobciążonej maszynie albo w CI.
