# Audyt responsywności 07 — Ustawienia, Kalendarz, Pomoc, Profil, Onboarding, Pule talentów, Zgłoszenia, komponenty etapów, dzwonek

Zakres: `src/app/settings/**`, `src/components/settings/**`, `src/app/calendar/**` + `src/components/calendar/**`,
`src/app/help/**` (→ `components/v2/pages/HelpPageV2.tsx`, `HelpClientPlaybooksSection.tsx`, `ProcedureTableOfContents.tsx`),
`src/app/profile/**`, `src/app/onboarding/**` (→ `OnboardingDLV2`/`OnboardingRecruiterV2`), `src/app/microsoft365/**`,
`src/app/applications/**`, `src/app/seeking/**` (przekierowanie), `src/app/talents/**`, `src/app/my-relationships` (przekierowanie),
`ScorecardSchemaBuilder`, `StageNotificationRulesModal`, `StageRuleForm`, `NotificationsDropdown`.

Metoda: statyczny odczyt kodu, bez uruchamiania. Punkty przerwania Tailwinda są domyślne (`globals.css` nie nadpisuje
`--breakpoint-*`). Kontekst powłoki (`AppShellV2.tsx:171-207`): pasek boczny aplikacji widoczny od `md` (768 px), treść
w `<div className="p-4 md:p-6">`, więc na 375 px strona ma ~343 px szerokości, na 768 px ~660 px (przy zwiniętym pasku).

Liczniki: **P0: 3 · P1: 9 · P2: 22**

---

## P0 — nieużywalne na telefonie

### P0-1. Widok „Tydzień” kalendarza: stały panel boczny 256 px + 7 kolumn dni, brak widoku dnia
- **Plik:** `src/components/calendar/WeekCalendar.tsx:270` (kontener `flex gap-0 h-[calc(100vh-220px)] … overflow-hidden`),
  `:819` (`CalendarSidebar` → `w-64 shrink-0 mr-4`), `:328` i `:499` (`grid grid-cols-[48px_repeat(7,1fr)]`).
- **Co się psuje:** panel boczny (mini-miesiąc, „Nadchodzące”, legenda, jedyny przycisk „Nowe wydarzenie”) nie ma żadnego
  wariantu `hidden …:flex`. Na 375 px zabiera 272 px, siatce zostaje ~70 px na kolumnę godzin (48 px) i 7 dni → ~3 px
  na dzień, wydarzeń nie da się ani przeczytać, ani trafić. Na 768 px (z paskiem aplikacji) dzień ma ~48 px — tytuły
  `truncate` znikają do 2–3 liter (**P1 na tablecie**). Kod nie przełącza się na widok dnia ani agendy przy wąskim ekranie.
  Linki z powiadomień `/calendar?event=` zawsze otwierają ten widok (`CalendarCycleScreen`), więc przypomnienie
  otwarte na telefonie ląduje w nieczytelnej siatce.
- **Poprawka:**
  - panel: `className="hidden lg:flex w-64 shrink-0 mr-4 flex-col gap-4"`; przycisk „Nowe wydarzenie” zdublować
    w nagłówku siatki z `lg:hidden`;
  - poniżej `md` renderować 1 dzień (`useMediaQuery('(min-width: 768px)')` → `days = isMd ? weekDays : [selectedDay]`,
    siatka `grid-cols-[40px_1fr]`, strzałki przesuwają dzień), albo najprościej: na `< md` przekierować `view=week`
    na Agendę;
  - na `md–lg` siatka `grid-cols-[40px_repeat(7,minmax(88px,1fr))]` w `overflow-x-auto` zamiast ściskania;
  - wysokość `h-[calc(100dvh-220px)]` zamiast `100vh` (pasek Safari).

### P0-2. Szablony e-maili (`/settings/templates`): dwa panele obok siebie bez zawijania
- **Plik:** `src/app/settings/templates/page.tsx:581` (`h-[calc(100vh-8rem)] flex flex-col`), `:627` (`flex-1 flex gap-4 min-h-0`),
  `:629` (lista `w-80 shrink-0`), `:730` (edytor `flex-1`).
- **Co się psuje:** lista ma sztywne 320 px i `shrink-0`; na 375 px edytor dostaje ~7 px (formularz nazwy, kategorii, tematu
  i treści jest niewidoczny). Na 768 px edytor ma ~320 px, a formularz ma w środku `grid grid-cols-2` (`:353`) → dwa pola po
  ~140 px (**P1 na tablecie**). Stała wysokość `100vh-8rem` + `overflow-hidden` dodatkowo obcina treść na krótkich ekranach.
- **Poprawka:** `flex flex-col lg:flex-row gap-4 min-h-0`; lista `w-full lg:w-80 lg:shrink-0 max-h-72 lg:max-h-none`;
  na `< lg` pokazywać naraz listę ALBO edytor (stan `selectedTemplate` → `hidden lg:flex` na liście, przycisk „← Szablony”);
  kontener `lg:h-[calc(100dvh-8rem)]` (bez sztywnej wysokości na telefonie); `:353` → `grid grid-cols-1 sm:grid-cols-2`.

### P0-3. Panel powiadomień (dzwonek w pasku górnym) wychodzi poza lewą krawędź ekranu
- **Plik:** `src/components/NotificationsDropdown.tsx:643` (`absolute right-0 top-full mt-2 w-96 …`).
- **Co się psuje:** panel ma sztywne 384 px i jest przypięty do prawej krawędzi przycisku, który stoi drugi od prawej
  w `TopbarV2.tsx:145` (za nim `QuickActionsV2`). Na 375 px prawa krawędź dzwonka jest ~60 px od krawędzi ekranu → lewe
  ~70 px panelu (ikona, nagłówek „Powiadomienia”, początek każdej treści) jest poza ekranem; na 414 px ~30 px. Dzwonek jest
  używany przez każdą rolę, to główny kanał pracy.
- **Poprawka:** `fixed inset-x-2 top-14 sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-2 w-auto sm:w-96`
  + lista `max-h-[min(420px,calc(100dvh-10rem))]`. Nagłówek (`:645`) dostać `flex-wrap gap-2`, a „Oznacz wszystko jako
  przeczytane” skrócić na mobile (`<span className="hidden sm:inline">jako przeczytane</span>`).

---

## P1 — zepsuty układ, przepełnienie, ukryta treść

### P1-1. Toast nowego powiadomienia wychodzi poza ekran
- **Plik:** `src/components/NotificationsDropdown.tsx:468` (`fixed bottom-6 right-6 z-300 max-w-sm w-full …`).
- **Co się psuje:** na 375 px `w-full` = 375 px przesunięte o `right-6` → lewe 24 px toastu poza ekranem.
- **Poprawka:** `fixed bottom-4 inset-x-4 sm:inset-x-auto sm:bottom-6 sm:right-6 sm:w-full max-w-sm`.

### P1-2. Okno „Dodaj/Edytuj użytkownika” bez przewijania i bez marginesu
- **Plik:** `src/components/settings/admin/UserModal.tsx:101-102` (`fixed inset-0 … flex items-center justify-center` +
  `w-full max-w-md p-6 space-y-5` — brak `p-4` na nakładce i brak `max-h`/`overflow-y-auto`).
- **Co się psuje:** formularz ma 7 bloków (imię, e-mail, hasło, rola podstawowa, dodatkowe role `max-h-44`, uprawnienie do
  usuwania klientów, rola legacy, przyciski) ≈ 700+ px. Na iPhonie SE (667 px), w orientacji poziomej i na laptopie z małą
  wysokością góra i dół okna (w tym „Zapisz”) są poza ekranem bez możliwości przewinięcia. Okno dotyka krawędzi ekranu.
  To samo, łagodniej, `ResetPasswordModal.tsx:29-30` (brak `p-4`).
- **Poprawka:** nakładka `p-4`, karta `max-h-[90dvh] overflow-y-auto` (albo przejście na `AppModal`/`DialogContent`,
  które już mają `max-h-[90vh]` i przewijaną treść).

### P1-3. Procesy rekrutacji (`PipelineTemplatesTab`): wiersz etapu i nagłówek szablonu nie zawijają
- **Plik:** `src/components/settings/PipelineTemplatesTab.tsx:364` (nagłówek: tytuł + checkbox „Domyślny proces” +
  „Klonuj” + „Archiwizuj” w `flex items-center justify-between` bez `flex-wrap`), `:441` (wiersz etapu `flex items-center gap-3`:
  uchwyt, numer, nazwa `flex-1`, chip kategorii, „Scorecard (n)”, „Powiadomienia”, „Zmień nazwę”, usuń).
- **Co się psuje:** na 375 px nagłówek potrzebuje ~360 px na przyciski → tytuł ściśnięty do minimum, całość wychodzi poza
  kartę. Wiersz etapu ma ~400 px elementów o stałej szerokości → nazwa etapu ma 0–40 px, wiersz przepełnia kartę. Na 768 px
  (`md:grid-cols-4`, treść `md:col-span-3` ≈ 500 px) nazwa etapu ma ~60 px.
- **Poprawka:** nagłówek `flex flex-wrap items-start justify-between gap-3`; wiersz etapu `flex flex-wrap items-center gap-x-3 gap-y-1.5`,
  nazwa `min-w-0 flex-1 basis-40 truncate`, przyciski w osobnym `div className="flex items-center gap-1 ml-auto"`;
  na mobile etykiety „Scorecard”/„Powiadomienia” jako ikony (`<span className="hidden sm:inline">`); układ `lg:grid-cols-4` zamiast `md:`.

### P1-4. Pule talentów: wiersz kandydata w puli przepełnia się na telefonie
- **Plik:** `src/app/talents/page.tsx:458-462` (`flex items-center justify-between px-6 py-4` → lewy blok `flex items-center gap-4`
  bez `min-w-0 flex-1`), `:508` (prawy blok `shrink-0`: chip „Z CV → Klient”, status, kosz).
- **Co się psuje:** na 375 px prawy blok zajmuje ~220 px, lewy (awatar 40 px + imię, kategoria, miasto, 4 umiejętności)
  nie może się skurczyć poniżej najdłuższego słowa → wiersz wychodzi poza kartę, imię łamie się po literach lub wystaje.
- **Poprawka:** wiersz `flex flex-col sm:flex-row sm:items-center gap-3 px-4 sm:px-6`; lewy blok `flex min-w-0 flex-1 items-center gap-4`,
  imię `truncate`; prawy `flex flex-wrap items-center gap-2 sm:shrink-0`.

### P1-5. Kalendarz → Agenda: wybór kandydata na telefonie nie daje widocznej reakcji
- **Plik:** `src/components/calendar/cycle/AgendaView.tsx:92` (`grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)] xl:grid-cols-[…_360px]`),
  `:208-220` (karta kandydata `aside` jako ostatni element siatki), `:121` (klik w „Do zrobienia” → `onSelect`).
- **Co się psuje:** poniżej `lg` (także tablet 768–1023) karta z 7 krokami cyklu i akcjami renderuje się pod całą listą
  „Do zrobienia” i całą agendą. Tapnięcie pozycji zmienia tylko tło wiersza; karta pojawia się setki pikseli niżej,
  więc wygląda to jak martwy klik. Brak `scrollIntoView` w `src/components/calendar/`.
- **Poprawka:** na `< lg` karta w `Sheet`/`Drawer` od dołu (`side="bottom"`, `max-h-[85dvh] overflow-y-auto`), albo
  `ref.scrollIntoView({ behavior: 'smooth', block: 'start' })` po wyborze, gdy `!matchMedia('(min-width:1024px)').matches`.

### P1-6. Pomoc → Procedury/Klienci: to samo — wybrana procedura renderuje się pod listą
- **Plik:** `src/components/v2/pages/HelpPageV2.tsx:236` (`grid grid-cols-1 md:grid-cols-[320px_1fr]`), `:264` (klik → `setSelectedId`),
  `:303` (treść pod listą); `src/components/v2/pages/HelpClientPlaybooksSection.tsx:127`.
- **Co się psuje:** na 375 px lista procedur (wyszukiwarka + wszystkie pozycje) stoi nad treścią; kliknięcie pozycji nie
  przewija do treści, użytkownik nie widzi zmiany.
- **Poprawka:** na `< md` pokazywać listę ALBO treść (przycisk „← Wszystkie procedury”), albo `scrollIntoView` sekcji
  treści po wyborze.

### P1-7. Nowe wydarzenie: siatka typów `grid-cols-5` dla 6 typów z długimi etykietami
- **Plik:** `src/components/calendar/WeekCalendar.tsx:1129` (`grid grid-cols-5 gap-1.5`, etykiety z `calendar-config.tsx:18-55`:
  „Rozmowa kwalifikacyjna”, „Rozmowa u klienta”…).
- **Co się psuje:** na 375 px (arkusz od dołu, `p-6`) komórka ma ~60 px; słowo „kwalifikacyjna” (~80 px przy `text-xs`)
  wystaje poza przycisk. Nawet w `sm:max-w-lg` komórka ma ~90 px, więc wystaje i na desktopie. Szósty typ ląduje sam
  w drugim rzędzie.
- **Poprawka:** `grid grid-cols-2 sm:grid-cols-3 gap-1.5`, przycisk `min-h-10 break-words`.

### P1-8. Panel „iCal import” — sztywne 384 px
- **Plik:** `src/components/calendar/WeekCalendar.tsx:1366` (`absolute right-0 mt-1 w-96 …`).
- **Co się psuje:** wychodzi poza ekran poniżej ~420 px i jest przycinany przez `overflow-hidden` karty siatki (`:287`).
- **Poprawka:** `w-[min(24rem,calc(100vw-2rem))]` albo Popover z portalem.

### P1-9. Tabele Markdown w procedurach bez przewijania poziomego
- **Plik:** `src/components/v2/pages/HelpPageV2.tsx:477-482` (`ReactMarkdown` + `remarkGfm` w `prose`, bez własnego `table`).
- **Co się psuje:** „Zamówienia — instrukcja dla Delivery Leada” ma 41 wierszy tabel po 3–4 kolumny tekstu. Na 375 px
  (artykuł `p-6` → ~280 px) kolumna ma ~70 px; identyfikatory w `code` i długie słowa wychodzą poza artykuł i poszerzają
  siatkę (`grid-cols-1` = `minmax(auto,1fr)`), co daje przewijanie całej strony w poziomie.
- **Poprawka:** `components={{ table: (p) => <div className="overflow-x-auto"><table {...p} /></div> }}` w `ReactMarkdown`
  + `min-w-0` na `<section>` treści; artykuł `p-4 md:p-8`.

---

## P2 — kosmetyka i ergonomia

| # | Plik:linia | Element | Problem (szerokość) | Poprawka |
|---|---|---|---|---|
| P2-1 | `components/calendar/cycle/CycleBoard.tsx:50` | Tablica 7 kroków | `repeat(7,minmax(180px,1fr))` = ~1275 px → przewijanie poziome także na laptopie 1280 z paskiem; brak przyciągania kolumn na dotyku | `snap-x snap-mandatory` + `snap-start` na kolumnach; na `< md` rozważyć listę zgrupowaną po kroku |
| P2-2 | `components/calendar/cycle/CalendarCycleScreen.tsx:293-310` | Przełącznik „Zakres” (3 opcje dla admin/HoR) | ~360 px > 343 px; przyciski bez `whitespace-nowrap` łamią tekst w `h-8` (tekst wychodzi poza pigułkę) | `overflow-x-auto` na grupie + `whitespace-nowrap` na przyciskach; na mobile krótsze etykiety („Moi”, „Rekrutacje”, „Zespół”) |
| P2-3 | `components/calendar/WeekCalendar.tsx:293-310` | Poprzedni/następny tydzień, „Dzisiaj” | cele 28 px / ~24 px wysokości; strzałki bez `aria-label` | `p-2.5` (≥40 px) + `aria-label="Poprzedni tydzień"`/„Następny tydzień”; „Dzisiaj” `h-9` |
| P2-4 | `WeekCalendar.tsx:1148`, `EventDetailModal.tsx:593` | Pola „Od/Do” `datetime-local` | `grid-cols-2` → ~150 px na polu przy 375 px, wartość ucięta w Chrome/Android | `grid grid-cols-1 sm:grid-cols-2 gap-3` |
| P2-5 | `components/ui/dialog.tsx:59` (dotyczy `EventDetailModal`, `ScheduleInterviewModal`, `SlotDialogs`, `DebriefDialog`) | Okna dialogowe | `w-full` bez marginesu → okno od krawędzi do krawędzi na 375 px, zaokrąglenia ucięte | `w-[calc(100%-2rem)]` w prymitywie (zmiana przekrojowa — do uzgodnienia z audytem prymitywów) |
| P2-6 | `NotificationsDropdown.tsx:781` | „Nie pokazuj takich” (wyciszenie kategorii) | `opacity-0 group-hover:opacity-100` — na dotyku niewidoczne, ale klikalne w prawym dolnym rogu pozycji (przypadkowe wyciszenie; jest „Cofnij”) | `opacity-100 sm:opacity-0 sm:group-hover:opacity-100` lub `[@media(hover:none)]:opacity-100` |
| P2-7 | `app/settings/templates/page.tsx:703` | Kosz przy szablonie | tylko po najechaniu, na dotyku niewidoczny (potwierdzenie istnieje) | jak P2-6 |
| P2-8 | `app/settings/templates/page.tsx:583` | Nagłówek „Szablony emaili” + 2 przyciski | `flex justify-between` bez zawijania, ściśnięty na 375 px | `flex flex-wrap items-start justify-between gap-3` |
| P2-9 | `app/settings/rate-benchmarks/page.tsx:97` | Nagłówek + „Import CSV”/„Dodaj” | jw. | jw. |
| P2-10 | `app/settings/rate-benchmarks/page.tsx:315` | Formularz benchmarku `grid-cols-3` | pola ~95 px na 375 px | `grid grid-cols-1 sm:grid-cols-3`, `col-span-2` → `sm:col-span-2` |
| P2-11 | `app/settings/scoring/page.tsx:175` | Etykieta suwaka `w-64` w wierszu z suwakiem i polem liczby | na 375 px suwak ściśnięty do domyślnej minimalnej szerokości | wiersz `flex flex-wrap items-center gap-3`, etykieta `w-full sm:w-64` |
| P2-12 | `components/settings/admin/AdminUsersTab.tsx:194` | Nagłówek „Panel administracyjny” + „Dodaj użytkownika” (wariant nieosadzony) | brak `flex-wrap` | `flex flex-wrap items-center justify-between gap-3` |
| P2-13 | `AdminUsersTab.tsx:301, 373-410` | Tabela 7 kolumn, akcje w ostatniej | na telefonie akcje osiągalne dopiero po przewinięciu w poziomie; ikony 28 px | kolumna akcji `sticky right-0 bg-card`, ikony `p-2.5`; albo `md:hidden` karty jak w `PermissionsTab` |
| P2-14 | `components/settings/admin/PermissionsTab.tsx:1051-1052` | Wyjątki użytkowników: lista `max-h-[38rem]` + szczegóły | na `< lg` szczegóły pod 38rem listy, wybór bez przewinięcia | jak P1-5 (scroll/przełączanie widoków) |
| P2-15 | `HelpPageV2.tsx:238`, `HelpClientPlaybooksSection.tsx:128` | `md:sticky md:top-4` lista bez limitu wysokości | lista dłuższa niż ekran, a krótsza niż artykuł → dół listy niedostępny aż do końca artykułu | na `nav`: `md:max-h-[calc(100dvh-12rem)] md:overflow-y-auto` |
| P2-16 | `app/settings/cv-rules/page.tsx:300`, `app/settings/ai/page.tsx:199`, `app/settings/api-integration/page.tsx:414`, `app/settings/rate-benchmarks/page.tsx:96`, `app/applications/page.tsx:148` | Własne `p-6` / `container px-4 py-8` / `px-4 py-6` | podwójny odstęp z powłoką (`p-4 md:p-6`) → 263–295 px treści na 375 px | usunąć dopełnienie strony albo `p-0 md:p-…` |
| P2-17 | `app/settings/page.tsx:497` + `components/ui/input.tsx:19` (+ wszystkie pola `text-sm`/`text-xs` w zakresie) | Pola tekstowe < 16 px | iOS powiększa stronę przy fokusie (wyszukiwarka Ustawień ma `text-[15px]`) | w prymitywach `text-base sm:text-sm`; wyszukiwarka `text-base` |
| P2-18 | `components/ScorecardSchemaBuilder.tsx:211-226` | ▲/▼ kolejności pytań | goły tekst, cel ~12×14 px | przyciski `h-8 w-8` z ikonami `ChevronUp/Down` i `aria-label` |
| P2-19 | `ScorecardSchemaBuilder.tsx:146` | Nagłówek „Scorecard dla: {etap}” + „Podgląd wypełnienia” + X | bez zawijania; długa nazwa etapu ściska przycisk | `flex flex-wrap gap-2`, tytuł `min-w-0 truncate` |
| P2-20 | `app/talents/page.tsx:746-769` | Filtr kategorii `w-[220px]` + „Nowa pula” | 220+~120 px > 343 px, grupa bez `flex-wrap` | `flex flex-wrap gap-2`, `triggerWidthClass="w-full sm:w-[220px]"` |
| P2-21 | `app/settings/dictionaries/page.tsx:143` | Wiersz słownika: klucz `w-32` + etykieta + akcje | etykieta ~100 px na 375 px | klucz `hidden sm:block sm:w-32` albo wiersz `flex-wrap` |
| P2-22 | `app/profile/page.tsx:286` | Awatar 80 px obok siatki danych | na 375 px siatka ~190 px (e-mail łamany `break-all`) | `flex flex-col sm:flex-row items-start gap-4 sm:gap-6` |

Drobne, nieliczone: `api-integration/page.tsx:291` `client_id` w `font-mono` bez `break-all` (ekran techniczny, ukryty z menu);
`WeekCalendar.tsx:766` lista „+N” `w-48 right-0` w wąskiej kolumnie poniedziałku wchodzi pod krawędź karty z `overflow-hidden`.

---

## Co jest zrobione dobrze

- **Macierz uprawnień RBAC** (`PermissionsTab.tsx:597-700`): tabela ról × sekcji tylko `hidden md:block` z `min-w-[920px]`,
  przewijaniem w `Table` (`overflow-auto`) i przyklejoną pierwszą kolumną (`sticky left-0`); poniżej `md` osobne karty ról
  z polami `sm:grid-cols-2`. Pasek zapisu `sticky bottom-3 flex-wrap`. Wzorzec do skopiowania dla tabeli użytkowników.
- **Strona startowa Ustawień** (`settings/page.tsx:501, 455-471`): kafelki `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3`,
  wiersze obszaru `min-h-14` z `min-w-0`, ścieżka `SettingsBreadcrumb` z `flex-wrap`.
- Tabele administracyjne (`EventHistoryTab`, `ConflictsRegistryTab`, `PlacementExclusionsTab`, `NotificationDeliverySettings`,
  `AutoMatchOverview`, `cv-rules`, `rate-benchmarks`, `hiring-managers`, `clients-overview`, `team-structure`) są w
  `overflow-x-auto`; `cv-rules` ma przyklejoną kolumnę akcji `sticky right-0`. Zakładki `AdminUsersTab` przewijają się
  (`overflow-x-auto` + `w-max`), filtry zawijają się (`flex-wrap`).
- `team-structure`: siatki z `lg:`/`xl:`/`sm:`; `TeamsNotificationsCard`: `md:grid-cols-3`; `EmailTemplatesCard`: `Sheet w-full sm:max-w-2xl`.
- **Kalendarz — cykl:** nagłówek `flex-wrap`, agenda `lg:`/`xl:` z `min-w-0`, wiersze agendy `flex-wrap`, kroki `CycleStepper`
  z `min-h-[44px]`, tablica z przewijaniem poziomym zamiast ściskania, okno nowego wydarzenia jako arkusz od dołu na mobile
  (`items-end sm:items-center`, `max-h-[90vh] overflow-y-auto`), treść `EventDetailModal` przewija się w oknie.
- Prymityw `DialogFooter` układa przyciski w kolumnę na mobile (`flex-col-reverse sm:flex-row`), przycisk zamknięcia ma 44 px.
- `StageNotificationRulesModal` i `ScorecardSchemaBuilder`: nakładka `p-4`, `max-h-[90vh] overflow-y-auto`, przyklejony nagłówek/stopka.
- **Pomoc:** układ `grid-cols-1 md:grid-cols-[320px_1fr]`, spis treści jest w treści artykułu (nie w przyklejonym bocznym
  panelu), więc działa na telefonie; `prose-sm md:prose-base`.
- Onboarding (`max-w-3xl px-4`), Zgłoszenia (karty z `flex-wrap`, `truncate`), Pule talentów (siatki pul `sm/lg/xl`),
  Profil (`grid-cols-1 sm:grid-cols-2`, e-mail `break-all`, podpis „Zmień” pod awatarem jako alternatywa dla nakładki na hover).
- `/seeking`, `/my-relationships` to przekierowania, `/microsoft365/callback` to prosty komunikat — bez uwag.

## Poza zakresem / niesprawdzone

- `components/cv-rules/*` (edytor reguł CV otwierany z `/settings/cv-rules`) — 0 punktów przerwania w `CvRuleEditor.tsx`
  i `CvRuleHistoryTab.tsx`; niesprawdzone szczegółowo, warto objąć w audycie modułu CV.
- Ekrany ukryte z menu (`linkedin-metrics`, `client-portfolio-preview`, `chats`, `diagnostics`, `ImportTab`, `CloudTalkSettingsCard`)
  przejrzane tylko pobieżnie — tabele mają `overflow-x-auto` (poza `CloudTalkSettingsCard.tsx:205` i `diagnostics:167`,
  które są wąskie).
- Pasek górny (`TopbarV2`) poza samym dzwonkiem — zakres innego audytu.
