# Audyt responsywności — Klienci + Zamówienia

Zakres: `/clients` (lista, `ClientsListV2`), profil `/clients/[id]` (wszystkie zakładki), `components/client-profile/**` (w tym `orders/**`), `components/clients/**`, `components/orders/**`, `OrdersAndContractsTab`, `EditOrderDialog`, `ExtendOrderDialog`, `NewContractorOrderDialog`, `FrameworkContractsTab`, `RateCardsTab`, `KeyRelationshipDialog`, `AnalyticsTab`, `components/client-playbook/**`, `/my-clients`, `/my-relationships`, `/order-mail` (to dziś przekierowania), `components/order-mail/OrderMailQueue.tsx`.

Metoda: statyczny przegląd kodu (bez uruchamiania). Breakpointy domyślne Tailwind v4 (`globals.css` nie nadpisuje `--breakpoint-*`). Szerokości liczone od powłoki: `<main>` ma `p-4 md:p-6` (`AppShellV2.tsx:208`), pasek boczny 240 px rozwinięty / 60 px zwinięty.

Budżet szerokości przy 375 px:
- strona: 375 − 32 = **343 px**,
- treść zakładki profilu klienta (karta `border` + `p-6`): 343 − 2 − 48 = **~293 px**,
- wnętrze karty zamówienia (`px-5`): **~251 px**.

Uwaga do kwot: `Intl.NumberFormat("pl-PL")` rozdziela tysiące **twardą spacją** (U+00A0), więc „1 234 567 zł” nigdy się nie zawinie — to jest przyczyna kilku przepełnień niżej.

Podsumowanie: **P0: 0 · P1: 14 · P2: 19** (+ 2 uwagi przekrojowe o prymitywach spoza zakresu).

---

## P1 — rozjechany układ / przepełnienie / ukryta treść

### P1-1. Nagłówek profilu klienta — grupa akcji bez zawijania
- **Plik:** `src/app/clients/[id]/page.tsx:939` (grupa `flex items-center gap-2` ze statusem, „Edytuj” i „Usuń klienta”), kontekst `:926–932`.
- **Co się psuje:** przy 375 px blok tytułu ma ~221 px (293 − ikona 56 − gap 16). Grupa akcji (pigułka statusu ~70 + „Edytuj” ~65 + „Usuń klienta” ~105 + odstępy) ma ~250 px. Rodzic ma `flex-wrap`, więc grupa przeskakuje do nowej linii, ale sama się nie zawija → wystaje ~30 px poza kartę (karta ma `overflow-hidden`, więc „Usuń klienta” jest częściowo ucięte). Dotyczy osób z `can_delete_clients`.
- **Poprawka:** `:939` → `flex flex-wrap items-center gap-2`; `:926` `p-6` → `p-4 sm:p-6`; `:928` ikonę firmy `hidden sm:flex` (odzyskuje 72 px na telefonie).

### P1-2. Lista klientów — przyciski nagłówka bez zawijania
- **Plik:** `src/components/v2/pages/ClientsListV2.tsx:498`.
- **Co się psuje:** w zakładce „Nieaktywni” admin widzi trzy przyciski: „Czyszczenie listy” + „Eksport” + „Nowy klient” ≈ 375 px przy dostępnych 343 px → przepełnienie ~30 px, cała strona przewija się w poziomie (`<main>` ma `overflow-y-auto`, więc oś X też staje się przewijalna).
- **Poprawka:** `flex flex-wrap items-center gap-2`; ewentualnie etykiety `<span className="hidden sm:inline">` przy ikonach.

### P1-3. Kafel „Aktywne MRR” — kwota wychodzi poza kafel
- **Pliki:** `src/components/client-profile/SummaryBar.tsx:45` (`grid grid-cols-2`) + `src/components/StatsCard.tsx:98` (`text-xl … tabular-nums` bez `truncate`/łamania).
- **Co się psuje:** przy 375 px kafel ma ~140 px, po odjęciu `p-2.5`, ikony 28 px i `gap-3` na wartość zostaje ~80 px. „245 678,5 zł” w `text-xl` to ~125 px i przez twardą spację się nie łamie → tekst wychodzi za ramkę kafla.
- **Poprawka:** `SummaryBar` → `grid grid-cols-1 gap-3 min-[420px]:grid-cols-2`; w `StatsCard:98` dodać `text-lg sm:text-xl` i `break-words` (albo `truncate` z `title`).

### P1-4. Zakładka Analityka — kwoty KPI wychodzą poza kafle
- **Plik:** `src/components/AnalyticsTab.tsx:104` (`grid grid-cols-2 md:grid-cols-4`), wartość w `:179` (`text-xl font-semibold`, bez `min-w-0`/łamania).
- **Co się psuje:** przy 375 px kafel ma ~140 px (116 px po `p-3`). „Przychód lifetime” rzędu „12 345 678,5” w `text-xl` to ~130–140 px bez możliwości zawinięcia → przepełnienie kafla. Przy 768 px (`md:grid-cols-4`, ~150 px na kafel) ten sam problem dla dużych klientów.
- **Poprawka:** `grid grid-cols-1 min-[420px]:grid-cols-2 lg:grid-cols-4`; wartość `text-lg sm:text-xl tabular-nums break-words`.

### P1-5. Zakładka Projekty — akcje zjadają tytuł rekrutacji
- **Plik:** `src/app/clients/[id]/ProjectsTab.tsx:100` (`flex items-center gap-2 shrink-0` z „Dodaj”, „Przegrana”, statusem i linkiem), tytuł w `:92` (`truncate`).
- **Co się psuje:** przy 375 px wiersz ma ~290 px. Blok akcji `shrink-0` zajmuje ~230 px, ikona 32 px → na tytuł zostaje ~0–20 px, więc tytuł jest całkowicie ucięty do „…”. Wiersz jest nieczytelny.
- **Poprawka:** kontener wiersza (`:83`) → `flex flex-wrap items-center gap-3`; blok akcji → `flex w-full items-center justify-end gap-2 sm:w-auto sm:shrink-0` (na telefonie akcje schodzą pod tytuł).

### P1-6. Zakładka Delivery Lead (Opiekunowie) — długi e-mail rozpycha wiersz
- **Plik:** `src/app/clients/[id]/OwnersTab.tsx:250–265` (TAC) i analogicznie `:378` (DL).
- **Co się psuje:** lewa kolumna (`:252 flex items-center gap-3` i `:254 <div>`) nie ma `min-w-0 flex-1`, a e-mail (`:263`) to jedno „słowo”. Adres rzędu `katarzyna.nowakowska@b2bnetwork.pl` (~220 px w `text-xs`) + prawa strona z „Ustaw 1. priorytet” i koszem (~140 px) > 290 px → wiersz wystaje poza kartę. Plakietka „1. priorytet tego TAC-a” dokłada kolejne ~140 px.
- **Poprawka:** `li` → `flex flex-wrap items-center justify-between gap-2`; lewa kolumna `min-w-0 flex-1`; e-mail `truncate` (albo `break-all`); wiersz nazwiska `flex flex-wrap items-center gap-2`.

### P1-7. Cennik (RateCardsTab) — tabela 6 kolumn z `overflow-hidden`
- **Plik:** `src/components/RateCardsTab.tsx:404–405`.
- **Co się psuje:** kontener tabeli ma `overflow-hidden` zamiast `overflow-x-auto`. Przy 375 px (293 px) sześć kolumn z `px-3` się ściska; to, co się nie zmieści (okres, przyciski akcji w ostatniej kolumnie), jest **ucięte i niedostępne** — nie da się tego przewinąć.
- **Poprawka:** `overflow-x-auto rounded-xl border …`; tabela `min-w-[640px]`; kwoty i daty `whitespace-nowrap`.

### P1-8. Umowy ramowe — wiersz metadanych bez zawijania
- **Plik:** `src/components/FrameworkContractsTab.tsx:282` (`flex items-center gap-4 mt-1 text-xs`).
- **Co się psuje:** „od RRRR-MM-DD” + „do RRRR-MM-DD” + waluta + przycisk z pełną nazwą pliku (np. `Umowa_ramowa_CeZ_145_2025_podpisana.pdf`) w jednej niełamanej linii → przy 375 px wiersz wychodzi poza kartę, a kosz (`:306`) jest spychany.
- **Poprawka:** `flex flex-wrap items-center gap-x-4 gap-y-1`; przycisk pliku `min-w-0 max-w-full` z `<span className="truncate">`.

### P1-9. Umowy ramowe — formularze „Nowa umowa ramowa” / „Nowy aneks” bez przewijania
- **Plik:** `src/components/FrameworkContractsTab.tsx:490–493` i `:640–643` (`<form className="… max-w-md w-full p-6 space-y-3">`).
- **Co się psuje:** brak `max-h`/`overflow-y-auto`. Na telefonie z otwartą klawiaturą (albo w poziomie) formularz jest wyższy niż ekran, a przyciski zapisu na dole są poza zasięgiem — nie da się ich przewinąć, bo tło `fixed inset-0` nie scrolluje.
- **Poprawka:** do `<form>` dodać `max-h-[90dvh] overflow-y-auto` (docelowo przepisać na `AppModal`, jak zrobiono w `EditOrderDialog`).

### P1-10. Materiały klienta — trzy modale z `overflow-hidden` bez limitu wysokości
- **Plik:** `src/app/clients/[id]/MaterialsTab.tsx:402–403` (Dodaj one-pager), `:934–935` (Aplikuj szablon(y)), `:1064–1065` (Edytuj wymóg).
- **Co się psuje:** kontener ma `overflow-hidden` bez `max-h`. Najgorzej `:934` — lista szablonów (`templates.map`, ok. `:954`) nie ma limitu, więc przy wielu szablonach stopka z przyciskami „Anuluj/Aplikuj” jest ucięta nawet na laptopie o małej wysokości, a na telefonie na pewno. Dwa pozostałe modale: ten sam problem przy otwartej klawiaturze.
- **Poprawka:** kontener `flex max-h-[90dvh] flex-col overflow-hidden`; część środkowa (`<form className="p-5 …">` / `<div className="p-5 space-y-3">`) `min-h-0 flex-1 overflow-y-auto`; stopka `shrink-0`.

### P1-11. `ModalShell` (Zakończ kontrakt, Zamknij jako przegraną, Dodaj kandydata) — bez marginesu i przewijania
- **Plik:** `src/components/client-profile/actions/CloseJobAsLostModal.tsx:107–111` (`ModalShell` używany też w `TerminateContractModal.tsx:55` i `AddCandidateToJobModal.tsx:74`).
- **Co się psuje:** tło nie ma `p-4`, więc przy 375 px okno (`max-w-md w-full`) dotyka krawędzi ekranu, a zaokrąglone rogi są ucięte. Brak `max-h`/`overflow-y-auto`: „Zakończ kontrakt” ma listę powodów (`CONTRACT_TERMINATION_REASONS.map`) + datę + notatkę → na telefonie z klawiaturą przycisk potwierdzenia jest poza ekranem.
- **Poprawka:** tło `… p-4`; panel `max-h-[90dvh] overflow-y-auto`; najlepiej przepisać `ModalShell` na `AppModal` (fokus, Esc, scroll lock za darmo).

### P1-12. Skrzynka zamówień z maila — zakładki statusu bez zawijania
- **Plik:** `src/components/order-mail/OrderMailQueue.tsx:405` (`<div className="mt-4 flex gap-2" role="tablist">`, etykiety w `:50–55`).
- **Co się psuje:** cztery przyciski „Do weryfikacji (N)”, „Zapisane automatycznie”, „Zapisane ręcznie”, „Nierozpoznane” mają razem ~560 px. W 343 px kurczą się do najdłuższego słowa — etykiety łamią się na dwie linie, a suma minimalnych szerokości (~375 px) i tak przekracza ekran → poziomy scroll całej strony.
- **Poprawka:** `mt-4 flex flex-wrap gap-2` (albo `overflow-x-auto` + `whitespace-nowrap shrink-0` na przyciskach — spójnie z `TabbedNav overflow="scroll"`).

### P1-13. Skrzynka zamówień — lista i szczegóły na telefonie
- **Plik:** `src/components/order-mail/OrderMailQueue.tsx:430` (`grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]`), wybór pozycji w `:436–451`.
- **Co się psuje:** poniżej 1024 px szczegóły renderują się POD całą listą. Kliknięcie pozycji zmienia tylko podświetlenie — szczegóły z przyciskami „Zastosuj/Odrzuć” lądują ekran lub kilka ekranów niżej, bez przewinięcia. Na telefonie i tablecie wygląda to jak „kliknięcie nic nie robi”.
- **Poprawka:** po wyborze pozycji `document.getElementById("order-mail-detail")?.scrollIntoView({ block: "start" })` tylko poniżej `lg` (`matchMedia("(max-width: 1023px)")`), albo na mobile pokazywać szczegóły zamiast listy z przyciskiem „← Wróć do listy”.

### P1-14. Baza wiedzy o kliencie — usuwanie widoczne tylko po najechaniu
- **Plik:** `src/app/clients/[id]/page.tsx:344` (`DeleteButton … className="opacity-0 group-hover:opacity-100 …"`).
- **Co się psuje:** na dotyku (telefon, tablet, iPad z Safari) nie ma hovera — przycisk usuwania wpisu jest niewidoczny i praktycznie nieosiągalny. Klawiatura też go nie „odkrywa” (brak `focus-visible:opacity-100`).
- **Poprawka:** `opacity-100 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100 focus-visible:opacity-100`.

---

## P2 — kosmetyka / ergonomia

### P2-1. Tabela konsultantów w profilu — ściskanie zamiast przewijania
- **Plik:** `src/components/client-profile/ConsultantsTable.tsx:74–88`, komórki kwot `:198–220`.
- **Stan:** wrapper `overflow-x-auto` jest (dobrze), ale tabela `w-full` bez `min-w`. Przy 375–768 px 5–7 kolumn ściska się: nagłówki „Stawka przychodowa [godz.]” łamią się na 3 linie, a nazwisko ląduje w wąskiej kolumnie. Brak przyklejonej kolumny „Konsultant” — po przewinięciu w bok nie wiadomo, czyj to wiersz.
- **Poprawka:** tabela `min-w-[720px]`; komórki liczbowe `whitespace-nowrap`; pierwsza kolumna `sticky left-0 z-10 bg-card` (th i td). Ewentualnie `<ul>` z kartami poniżej `md`.

### P2-2. Lista klientów — tabela 900 px bez wersji mobilnej
- **Plik:** `src/components/v2/pages/ClientsListV2.tsx:692` (`<Table … className="min-w-[900px]">`, wrapper `overflow-auto` w `ui/table.tsx:27`).
- **Stan:** działa (przewijanie w bok), ale na telefonie widać ~⅓ tabeli, bez przyklejonej kolumny „Firma”.
- **Poprawka:** `sticky left-0 bg-card` na pierwszej kolumnie albo lista kart `md:hidden` + tabela `hidden md:block`.

### P2-3. Lista klientów — kafle kategorii zajmują ~330 px wysokości na telefonie
- **Plik:** `ClientsListV2.tsx:622` (`grid grid-cols-1 … md:grid-cols-2`), kafel `:646` (`min-h-24 p-4`) z opisem `:668`.
- **Poprawka:** poniżej `sm` `grid-cols-3`, opis `hidden sm:block`, `min-h-0 sm:min-h-24`, liczba pod tytułem.

### P2-4. Informacje dostępne tylko w tooltipie / atrybucie `title`
- `ClientsListV2.tsx:700–716` („Status klienta” z ikoną Info) i ikony `cursor-help` w wierszach (`:905–915`) — Radix Tooltip nie otwiera się dotykiem.
- `StatsCard.tsx:94` — podpis kafla (np. „suma niepełna: pominięto N kontraktów bez stawki” z `SummaryBar.tsx:41`) jest tylko w `title`, którego na dotyku nie ma. Tytuł mówi co prawda „(niepełne)”, ale bez liczby i powodu.
- **Poprawka:** Popover na kliknięcie zamiast Tooltip dla treści merytorycznych; w `StatsCard` podpis jako `<p className="text-xs text-muted-foreground sm:sr-only">` na mobile.

### P2-5. Pasek zakładek profilu — brak przewinięcia do aktywnej
- **Plik:** `src/app/clients/[id]/page.tsx:1001–1024`.
- **Stan:** `overflow-x-auto whitespace-nowrap min-w-0` + `shrink-0` — dobrze. Przy 375 px 8 zakładek ma ~900 px; wejście z powiadomienia (`?tab=zamowienia`, `?tab=analityka`) nie przewija paska do aktywnej zakładki, a brak gradientu na krawędzi nie sugeruje dalszych zakładek.
- **Poprawka:** `ref` na aktywnym przycisku + `scrollIntoView({ inline: "nearest", block: "nearest" })` w efekcie na `activeTab`; opcjonalnie maska `[mask-image:linear-gradient(to_right,black_90%,transparent)]` poniżej `md`.

### P2-6. Padding karty profilu
- `page.tsx:926` i `:1029` — `p-6` na telefonie zabiera 48 px z 343. → `p-4 sm:p-6` (zyskuje 16 px dla każdej zakładki, w tym zamówień).

### P2-7. Formularze w dwóch kolumnach bez wariantu mobilnego
Przy 375 px kolumna ma 120–145 px; etykiety typu „Początek zamówienia (PDF od klienta)” łamią się na 3 linie i pola stają w różnej wysokości.
- `src/app/clients/[id]/page.tsx:275, 397, 417, 436` (wiedza, kontakty — e-mail/telefon po ~120 px),
- `src/components/EditOrderDialog.tsx:564, 590, 615, 641`,
- `src/components/ExtendOrderDialog.tsx:356, 395`,
- `src/components/NewContractorOrderDialog.tsx:722, 752, 783`,
- `src/components/FrameworkContractsTab.tsx:506, 533`,
- `src/app/clients/[id]/MaterialsTab.tsx:1102`,
- `src/components/order-mail/OrderMailQueue.tsx:672` (`dl grid-cols-2 gap-x-6`).
- **Poprawka:** `grid grid-cols-1 gap-3 sm:grid-cols-2`.

### P2-8. Zoom iOS przy fokusie pól `text-sm` (14 px)
Brak globalnej reguły 16 px na mobile (`globals.css`), a `ui/input.tsx:19` i `ui/select.tsx:19` mają `text-sm`. W zakresie dotyczy m.in.: `OrderGroupFormModal.tsx:56–57`, `ConsultantLineModal.tsx:44–45`, `ConsultantPicker.tsx:10–11`, `OrderListControls.tsx` (pola dat i select, `:98–137`), `EditOrderDialog.tsx` (pola `text-sm`), `page.tsx` formularze wiedzy i kontaktów, `MaterialsTab.tsx`, `ClientPlaybookForm.tsx:289, 298`, wyszukiwarka listy klientów (`ClientsListV2.tsx` → `Input`).
- **Poprawka (przekrojowa):** w klasach pól `text-base sm:text-sm` (najlepiej raz w `ui/input.tsx`/`ui/select.tsx` i w lokalnych stałych `inputClass`).
- Dobrze: `OrderPlanLineCard.tsx:27` (`text-base`), `NewContractorOrderDialog`/`ExtendOrderDialog` (pola bez `text-sm` = 16 px).

### P2-9. Cele dotykowe < 40 px
- `OrderGroupCard.tsx:663–710` — ikony wiersza (Edytuj, Zamień, Usuń, Rozliczenia `:620`) `p-1.5` + `h-4` = 28 px.
- `OrderPlanLineCard.tsx:244` — kosz karty `p-1` = 24 px.
- `OrdersAndContractsTab.tsx:1388, 1404, 1415, 1426` — przyciski akcji kontraktora `px-2 py-1 text-xs` ≈ 26 px; kosze `:1613`, `:1748` `p-1`; pola w linii `:1226` `py-0.5`.
- `page.tsx:692–713` — serce/ołówek przy kontakcie: goła ikona 16 px bez paddingu.
- `FrameworkContractsTab.tsx:306` (kosz `p-1`), `OwnersTab.tsx:283` (kosz bez paddingu), `MaterialsTab.tsx:407` (zamknięcie `p-1`), linki mail/telefon `KeyRelationshipsPanel.tsx:171–186` i `page.tsx:667–683` (`text-xs` + ikona 12 px).
- **Poprawka:** `inline-flex h-10 w-10 items-center justify-center` (albo `p-2.5` + `-m-1` żeby nie zmieniać wizualnego rytmu) poniżej `sm`: `h-10 w-10 sm:h-8 sm:w-8`.

### P2-10. Karta planu zamówienia — breakpoint wiewportu w wąskim modalu
- **Plik:** `OrderPlanLineCard.tsx:251` (`sm:grid-cols-2 lg:grid-cols-4` przy MD).
- **Co się psuje:** karta żyje w `AppModal size="lg"` (max 672 px). Od 1024 px wiewportu przełącza się na 4 kafle po ~145 px w oknie, które się nie poszerzyło — etykieta, wartość, sufiks „zł/MD” i podpowiedź się ściskają.
- **Poprawka:** usunąć `lg:grid-cols-4` albo przejść na container queries: rodzic `@container`, kafle `@2xl:grid-cols-4`.

### P2-11. Filtry zamówień — daty po ~106 px przy 1280 px
- **Plik:** `OrderListControls.tsx:92` (`md:grid-cols-2 xl:grid-cols-4`), fieldsety `:93`, `:117` (`grid grid-cols-2`) z `type="date"` `px-2`.
- **Co się psuje:** przy 1280 px z rozwiniętym paskiem (240 px) sekcja ma ~916 px → 4 fieldsety po ~220 px → każde pole daty ~106 px (≈88 px wnętrza). W Chrome „dd.mm.rrrr” + ikona kalendarza ledwo się mieszczą albo ostatnie cyfry są ucięte.
- **Poprawka:** `xl:grid-cols-4` → `2xl:grid-cols-4`.

### P2-12. Notatka relacji w kontakcie — sprzeczne wcięcia
- `page.tsx:718` — `pl-12 … pl-3 ml-12`: `pl-12` jest martwe, `ml-12` zabiera 48 px na telefonie. → `ml-0 sm:ml-12 pl-3`.

### P2-13. Długie e-maile kontaktów bez łamania
- `page.tsx:665–683`, `KeyRelationshipsPanel.tsx:169–186` — link e-mail to jedno słowo; przy długim adresie wychodzi poza kartę (rodzic ma `min-w-0`, ale tekst nie ma `break-all`/`truncate`). → `break-all` albo `truncate max-w-full`.

### P2-14. Szczegóły dokumentu z maila — tabela bez wrappera
- `OrderMailQueue.tsx:678` (`<table className="mt-2 w-full text-sm">`, 4 kolumny, kwoty z twardą spacją + dopisek „brutto ÷ 1,23”). Na telefonie może wypchnąć sekcję szczegółów w bok. → `<div className="mt-2 overflow-x-auto">` + `min-w-[520px]` na tabeli.

### P2-15. Surowe modale zamówień (`fixed inset-0`) — `vh` zamiast `dvh`, stopka nieprzyklejona
- `NewContractorOrderDialog.tsx:436/460`, `ExtendOrderDialog.tsx:284/294`, `KeyRelationshipDialog.tsx:75/81` — `max-h-[90vh] overflow-auto` na całym formularzu. Na iOS `vh` = duży wiewport, więc przy widocznych paskach Safari dół okna bywa pod paskiem; przyciski „Anuluj/Zapisz” są na samym końcu długiego formularza (NewContractorOrderDialog ma kilkanaście pól), a tło przewija stronę pod spodem (brak scroll-lock).
- **Poprawka:** `max-h-[90dvh]`; najlepiej przepisać na `AppModal` (stały nagłówek i stopka, przewijane body — tak jak `EditOrderDialog.tsx:466`).

### P2-16. Karta klienta (playbook) — pola dokumentów
- `ClientPlaybookForm.tsx:289` (`w-56`) i `:298` (`min-w-64 flex-1`) w `flex-wrap` — przy 375 px (`~261 px` wnętrza) `min-w-64` (256 px) jest na granicy; każda dodatkowa ramka/padding powoduje przepełnienie. → `w-full sm:w-56` i `min-w-0 w-full sm:min-w-64`.

### P2-17. Strona listy — wyszukiwarka i przełącznik
- `ClientsListV2.tsx:578` (`w-full max-w-lg`) — OK; pomocnik pod polem i przełącznik „Moi/Wszyscy” zawijają się poprawnie. Jedyna uwaga: przycisk czyszczenia `h-7 w-7` (28 px) — `:604`.

### P2-18. Nagłówek karty zamówienia na telefonie
- `OrderGroupCard.tsx:1169–1238` — przycisk rozwijania z do 5 awatarami + „+N” (~150 px) i `gap-4` zostawia ~100 px na „Zamówienie nr …” i okres przy 375 px (karta `px-5`). Numer się zawinie, ale nagłówek robi się wysoki. → poniżej `sm` pokazywać 3 awatary (`activeLines.slice(0, 3)` przez klasę `hidden sm:inline-flex` na 4–5.), `px-4 sm:px-5`.

### P2-19. `ContractorOrderCards` — przyciski akcji kontraktora
- `OrdersAndContractsTab.tsx:1379` (`flex flex-wrap items-center gap-1.5 shrink-0`) obok bloku `:1106 flex-1 basis-80 min-w-0` — zawija się poprawnie, ale na telefonie cztery przyciski `text-xs py-1` tworzą dwa rzędy małych celów (patrz P2-9). → poniżej `sm` menu „⋯” (Popover) z akcjami.

---

## Uwagi przekrojowe (prymitywy spoza zakresu, wpływają na wszystkie okna tutaj)

- **`src/components/ui/dialog.tsx` (DialogContent):** `w-full` + `max-w-*` bez marginesu → przy 375 px każde okno `md`/`lg`/`xl` (w tym `OrderGroupFormModal`, `ConsultantLineModal`, `LineMonthlyHistoryDialog`) jest od krawędzi do krawędzi z uciętymi zaokrągleniami. Poprawka: `w-[calc(100%-2rem)]` (albo `max-w-[calc(100vw-2rem)]`). Na telefonie warto rozważyć arkusz od dołu (`bottom-0 top-auto translate-y-0 rounded-b-none` poniżej `sm`).
- **`max-h-[90vh]`** w tym samym prymitywie → `max-h-[90dvh]` (iOS Safari: `vh` liczy duży wiewport, stopka z przyciskiem zapisu może chować się pod paskiem narzędzi).

---

## Co już jest zrobione dobrze

- **Okna na `AppModal`** (`OrderGroupFormModal`, `ConsultantLineModal`, `ExtendOrderGroupModal`, `SwapConsultantModal`, `OffboardingDecisionModal`, `LineMonthlyHistoryDialog`, `EditOrderDialog`, `DeleteOrderDialog`, `DeleteClientDialog`, `InactiveClientsCleanupDialog`…): nagłówek i stopka stałe, body `overflow-y-auto flex-1 min-h-0`, stopka `flex-col-reverse sm:flex-row` (przyciski w pełnej szerokości na telefonie), zamknięcie 44×44 px. Formularz „Nowe zamówienie” z wieloma kartami osób przewija się w środku, a „Utwórz zamówienie” jest zawsze widoczny.
- **Siatki formularzy zamówień** są już mobilne: `grid-cols-1 sm:grid-cols-2` (`ConsultantLineModal.tsx:881, 1059`, `OrderGroupFormModal.tsx:1076`, `ExtendOrderGroupModal.tsx:423`, `OffboardingDecisionModal.tsx:242`), `sm:grid-cols-3` (`SwapConsultantModal.tsx:187`, `LineMonthlyHistoryDialog.tsx:334`), `ExtendOrderDialog.tsx:446` i `NewContractorOrderDialog.tsx:843` z wariantem `sm:`.
- **Wiersz obsady zamówienia** (`OrderGroupCard.tsx:838`) jest `flex-wrap` z podłogami `min-w-[13rem]/[15rem]`, które mieszczą się w 251 px; karta konsultanta CeZ (`:807`, `:979`) składa się do jednej kolumny poniżej `sm`; segmentowany wybór w `ConsultantLineModal.tsx:156` ma `max-w-full flex-wrap`.
- **Tabele z poziomym przewijaniem:** `ConsultantsTable` (`overflow-x-auto`), `LineMonthlyHistoryDialog.tsx:224` (+ `truncate max-w-[10rem]` na długich polach), `ExecutiveContractReviewPanel.tsx:97`, historia sprawdzeń skrzynki `OrderMailQueue.tsx:247`, lista klientów `min-w-[900px]` w `overflow-auto`.
- **Paski narzędzi i zakładki:** `OrderListControls.tsx:54` (`flex-col sm:flex-row`), nagłówek i pigułki `MultiConsultantOrdersTab.tsx:1000, 1041` (`flex-wrap`), `ContractStructureSection` i `ExecutiveContractFilter` (`flex-wrap`), pasek zakładek profilu z `overflow-x-auto whitespace-nowrap min-w-0` i `shrink-0`, `TabbedNav` z trybem `scroll`.
- **Pola z kwotami na kartach planu** mają `text-base` i `min-w-0` (brak zoomu iOS, brak rozpychania) — `OrderPlanLineCard.tsx:27, 107`; `ConsultantPicker` ma listę `max-h-56 overflow-y-auto` i `truncate` na nazwiskach.
- **Paginacja listy klientów** `flex-col sm:flex-row` (`ClientsListV2.tsx:956`), kategorie `md:grid-cols-2 lg:grid-cols-3`, skrzynka zamówień `lg:` master-detail z `minmax(0, …)` (bez rozpychania przez długie treści).
- **Karta klienta (playbook):** `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3` i `md:grid-cols-2` (`ClientPlaybookForm.tsx:158, 229, 435`), podgląd Markdown z `max-h-[400px] overflow-y-auto`.
- **Stare adresy** `/my-clients`, `/my-relationships`, `/order-mail` przekierowują serwerowo — nie ma tam osobnych widoków do utrzymania.

---

## Top 10 do naprawy (kolejność)

1. P1-5 `ProjectsTab.tsx:100` — tytuł rekrutacji ucięty do zera na telefonie.
2. P1-3 / P1-4 `SummaryBar.tsx:45` + `StatsCard.tsx:98`, `AnalyticsTab.tsx:104` — kwoty wychodzą z kafli.
3. P1-7 `RateCardsTab.tsx:404` — `overflow-hidden` ucina kolumny cennika.
4. P1-10 `MaterialsTab.tsx:934` — lista szablonów bez limitu, przyciski poza oknem.
5. P1-9 `FrameworkContractsTab.tsx:490, 640` i P1-11 `CloseJobAsLostModal.tsx:107` — formularze bez przewijania.
6. P1-13 `OrderMailQueue.tsx:430` — wybór dokumentu na telefonie „nic nie robi”.
7. P1-12 `OrderMailQueue.tsx:405` — zakładki statusu rozpychają stronę.
8. P1-1 `page.tsx:939` i P1-2 `ClientsListV2.tsx:498` — grupy przycisków bez `flex-wrap`.
9. P1-6 `OwnersTab.tsx:250, 378` i P1-8 `FrameworkContractsTab.tsx:282` — długie e-maile i nazwy plików rozpychają wiersze.
10. P1-14 `page.tsx:344` — usuwanie wpisu wiedzy tylko na hover.
