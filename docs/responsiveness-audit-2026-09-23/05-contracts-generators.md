# Audyt responsywności — Kontrakty, umowy, generatory (05)

Zakres: `/contracts` (rejestr globalny, rejestr klienta, „Obsługa kontraktorów”, `?view=order-mail`), `/contracts/[id]` + zakładki (Dokumenty, Aneksy, Onboarding, Sprzęt, Notatki, Faktury, Historia stawek, Timeline), `/contracts/new`, `/contracts/analytics`, `/contractors` (redirect), Generator Umów B2B (`B2BContractGeneratorV2.tsx` + dialogi), `/sign/[token]`, `/engagement/[token]`, `/cv-generator` (`CVGeneratorStandaloneV2.tsx`, `CVBrandedEditModal`, kafelki), `src/components/cv-rules/**`, publiczne CV `/cv/[token]` i `/cv/i/[token]`.

Metoda: statyczny odczyt kodu (bez uruchamiania). Breakpointy domyślne Tailwind v4 (brak nadpisań w `@theme` w `src/app/globals.css`, brak `tailwind.config.*`).

## Kontekst wymiarów (ważne dla wszystkich ustaleń)

- Shell (`src/components/v2/shell/AppShellV2.tsx:207-208`): `<main class="overflow-y-auto">` + `p-4 md:p-6`. Sidebar: ukryty < 768 px, od `md` 60 px (zwinięty) albo 240 px (rozwinięty).
- Szerokość treści: **375 px → 343 px**, **768 px → ~660 px**, **1280 px → ~1172 px** (zwinięty) / ~992 px (rozwinięty), **1920 px → ~1812 px**.
- `main` ma `overflow-y-auto`, więc każde przepełnienie w poziomie daje **poziomy scroll całej strony** (w `main`), nie ucięcie.
- Globalnie: `ui/input.tsx:19`, `ui/select.tsx:19`, `ui/textarea.tsx:16` i `globals.css:541-551` wymuszają `text-sm` (14 px) na polach → **iOS Safari zoomuje przy fokusie** w każdym formularzu (dotyczy też stron publicznych).
- `ui/dialog.tsx:59`: `DialogContent` ma `w-full` + `max-w-*` bez marginesu → na 375 px okno dotyka krawędzi ekranu (zaokrąglenia i ramka ucięte). Przycisk zamknięcia `absolute right-4 top-4 h-11 w-11` (44 px — dobrze), ale nakłada się na własne nagłówki niektórych okien (niżej).

## Podsumowanie

| Waga | Liczba |
|---|---|
| **P0** (nieużywalne na telefonie/tablecie) | 1 |
| **P1** (rozjechany układ / przepełnienie / ukryta treść) | 19 |
| **P2** (kosmetyka / ergonomia) | 18 (17 w sekcji P2 + P1-20, które mieści się na granicy) |

---

## P0

### P0-1. Publiczne CV (`/cv/i/[token]`, `/cv/[token]`) — brandowany HTML ma sztywną siatkę 230 px + 1fr, na telefonie kolumna treści ma ~47 px
- **Pliki:** `src/app/cv/i/[token]/page.tsx:874-878` (iframe `srcDoc={view.cv_html}`), `src/app/cv/[token]/page.tsx:133-140`; źródło HTML: `backend/app/services/cv_html_renderer.py:338-350` (`.cv-body { display:grid; grid-template-columns: 230px 1fr }`, `.cv-main { padding: 28px 32px }`, `.cv-header { padding: 32px 40px }`) — **brak jakiegokolwiek `@media` poza `print`**. Ten renderer (`_generate_cv_html`) tworzy `branded_draft_html`/`content_html`, który publiczne endpointy (`public_share.py:292`, `:515`) serwują jako `cv_html`.
- **Co się psuje:** przy 375 px iframe ma ~341 px. Kolumna boczna zabiera 230 px, na doświadczenie zostaje 111 px minus 64 px paddingu = **~47 px na tekst** — słowo na linię, CV nieczytelne. Na 768 px (tablet, ~720 px iframe) kolumna główna ~490 px — OK. Klient otwiera link z maila najczęściej na telefonie, to jest jego pierwszy kontakt z kandydatem.
- **Naprawa:**
  1. Backend (nowe dokumenty): w `cv_html_renderer.py` dopisać
     `@media (max-width: 640px){ .cv-body{grid-template-columns:1fr} .cv-sidebar{border-right:0;border-bottom:1px solid #e2e8f0;padding:20px 16px} .cv-main{padding:20px 16px} .cv-header{padding:24px 16px} .cv-footer{padding:12px 16px;flex-wrap:wrap;gap:4px} }`.
  2. Frontend (dokumenty już zamrożone po `finalize` — HTML jest niemutowalny): przy budowie `srcDoc` doklejać ten sam blok stylu, np. `srcDoc={MOBILE_CV_CSS + html}` z `const MOBILE_CV_CSS = "<style>@media (max-width:640px){.cv-body{grid-template-columns:1fr!important}…}</style>"` (sanitizer działa na backendzie, więc styl doklejony po stronie klienta przejdzie). Tak samo w `/cv/[token]`.

---

## P1

### P1-1. `/cv/[token]` — iframe CV o stałej wysokości = przewijanie w przewijaniu
- `src/app/cv/[token]/page.tsx:135-141`: `style={{ height: "calc(100vh - 220px)", minHeight: 600 }}` + kontener `overflow-hidden`.
- Na telefonie CV (np. 2500 px) przewija się wewnątrz ramki 600 px, a strona obok też się przewija — pułapka scrolla na dotyku. `/cv/i` robi to dobrze (`fitCvFrame`, `page.tsx:673-677`).
- **Naprawa:** skopiować `fitCvFrame` (onLoad → `scrollHeight`) z `/cv/i`; przyciski wersji językowych w tym kontenerze dostają `px-3 pt-3` (teraz przyklejone do ramki bez odstępu, `:134`).

### P1-2. Generator Umów B2B — podwójny padding + pasek zakładek bez przewijania
- `src/components/v2/pages/B2BContractGeneratorV2.tsx:501` `mx-auto max-w-7xl p-6` wewnątrz shellowego `p-4` → na 375 px treść ma 295 px (40 px marginesu z każdej strony).
- `:524-536` `TabsList` (`ui/tabs.tsx:15` `inline-flex … border-b`, bez `overflow-x-auto`, triggery bez `whitespace-nowrap`): 4 zakładki („Generator”, „Umowy bieżące”, „Umowy bez projektu”, „Zakończone umowy”) + admin „Zakresy ról (admin)”. Na 375 px etykiety łamią się na dwie linie, a suma min-content (~450 px) i tak przekracza szerokość → poziomy scroll całej strony. Na 768 px z zakładką admina (~700 px) na granicy.
- **Naprawa:** `p-0 md:p-6` (albo usunąć `p-6`, shell już daje padding); `TabsList className="mb-4 w-full justify-start overflow-x-auto"` + `TabsTrigger className="shrink-0 whitespace-nowrap"`.

### P1-3. B2B — pole wyszukiwania `min-w-[18rem]` rozpycha stronę na telefonie
- `B2BContractGeneratorV2.tsx:2032` i `:2600` `relative min-w-[18rem] flex-1`.
- Dostępne na 375 px: 343 − 48 (p-6) − 40 (Card p-5) ≈ 253 px < 288 px → ~35 px poziomego przepełnienia całej strony we wszystkich trzech zakładkach rejestru.
- **Naprawa:** `relative w-full min-w-0 flex-1 sm:min-w-[18rem]`; `SelectTrigger className="w-full sm:w-56"` (`:2049`).

### P1-4. B2B — rejestr: przyklejona kolumna akcji zasłania ~45% widocznej tabeli na telefonie
- `B2BContractGeneratorV2.tsx:2126-2167, 2398` (i `:2680-2757` w „bez projektu”/„zakończone”): 9 kolumn w `overflow-x-auto`, `th/td sticky right-0` z 3–4 ikonami `h-8 w-8`.
- Na 375 px widoczne okno tabeli ~253 px, kolumna akcji ~110–140 px → każda kolumna danych przesuwa się pod akcje; „Status podpisu” z przyciskiem „Oznacz jako podpisaną” praktycznie niewidoczny. Dodatkowo przyciski 32 px (< 40 px).
- **Naprawa:** przyklejanie tylko od `md` (`md:sticky md:right-0`), a < `md` widok kart (wzorzec z `ContractsListV2`: `max-md:block`, etykieta pola nad wartością); ikony `h-10 w-10 md:h-8 md:w-8`.

### P1-5. B2B — stawka progresywna i data rozpoczęcia: siatki bez breakpointów
- `B2BContractGeneratorV2.tsx:3928` `grid flex-1 grid-cols-3 gap-3` (stawka + „Obowiązuje od” + „Obowiązuje do”) obok przycisku kosza; `:3965` `grid grid-cols-3` dla samej waluty; `:3908` `grid grid-cols-2` (stawka + waluta).
- Na 375 px każda kolumna ~60 px → pola `type="date"` nieczytelne (data ucięta, ikona kalendarza nachodzi), etykiety „Stawka godz. (netto) — etap 2” łamią się na 3 linie i rozjeżdżają wyrównanie `items-end`.
- `:3883-3902` `flex gap-2`: `SelectTrigger w-[150px] shrink-0` + `Input type="date"` → na data zostaje ~95 px.
- **Naprawa:** `grid flex-1 grid-cols-1 gap-3 sm:grid-cols-3`; waluta `grid grid-cols-1 sm:grid-cols-3`; data rozpoczęcia `flex flex-col gap-2 sm:flex-row` + `SelectTrigger className="w-full sm:w-[150px] sm:shrink-0"`.

### P1-6. Kontrakt → „Historia stawek”: tabela w `overflow-hidden` — kolumny ucięte na telefonie
- `src/app/contracts/[id]/page.tsx:2269` `rounded-2xl … overflow-hidden` + `:2287` `<table className="w-full text-sm">` (5 kolumn, `px-4`).
- Na 343 px min-content (~450 px) przekracza szerokość; `overflow-hidden` ucina „Stawka”/„Notatka” bez możliwości przewinięcia.
- **Naprawa:** wrapper `overflow-x-auto` (zamiast/obok `overflow-hidden`), `<table className="w-full min-w-[32rem] text-sm">`.

### P1-7. Kontrakt → „Dokumenty”: kolumna akcji (Pobierz/Usuń) poza ekranem
- `src/components/ContractDocumentsTab.tsx:259` `overflow-hidden` + `:270-278` tabela 6 kolumn (Plik, Typ, Rozmiar, Ważny do, Dodano, Akcje).
- Na 375 px „Akcje” (jedyne miejsce usunięcia) są ucięte i nieosiągalne; ikony `p-1.5` = 28 px (`:342, :356` w bloku akcji).
- **Naprawa:** `overflow-x-auto` + `min-w-[36rem]` na tabeli, albo < `sm` ukryć „Rozmiar”/„Dodano” (`hidden sm:table-cell`); przyciski `p-2.5` (≥ 40 px).

### P1-8. Kontrakt → „Faktury”: to samo — akcje (oznacz jako opłaconą / usuń) ucięte
- `src/components/ContractInvoicesTab.tsx:232-242` `overflow-hidden` + 7 kolumn; akcje `p-1.5` (`:282, :293`).
- **Naprawa:** jak P1-7 (`overflow-x-auto`, `hidden sm:table-cell` dla „Kierunek”/„Wystawiona”).

### P1-9. Kontrakt → „Aneksy”: JSON „Przed/Po” rozpycha kartę
- `src/components/ContractAmendmentsTab.tsx:421` `<div className="flex-1">` (bez `min-w-0`) → `:433` `grid grid-cols-1 md:grid-cols-2` → `:437, :445` `<pre className="… overflow-x-auto">`.
- `overflow-x-auto` na `pre` nie działa, bo element flex/grid przyjmuje min-content najdłuższej linii JSON-a → cała lista aneksów wychodzi poza ekran (każdy aneks, zawsze rozwinięte). Na 375 px i często na 768 px.
- **Naprawa:** `flex-1 min-w-0` w `:421` i `min-w-0` na dzieciach siatki (`grid-cols-1 md:grid-cols-2 [&>*]:min-w-0`).

### P1-10. Kontrakt → „Timeline”: rozwinięte „Dane techniczne” rozpychają stronę
- `src/app/contracts/[id]/page.tsx:2343` `<div className="flex-1">` (bez `min-w-0`) + `:2381` `<pre … overflow-x-auto>`.
- Po rozwinięciu `<details>` długa linia JSON przepełnia całą kartę (mechanizm jak P1-9).
- **Naprawa:** `flex-1 min-w-0`.

### P1-11. Analityka kontraktów — rankingi marży ucięte na telefonie i przy 1024–1279 px
- `src/app/contracts/analytics/page.tsx:148` `overflow-hidden` + `:167-178` tabela 6 kolumn (#, nazwa, Aktywne, Przychód/mies., Marża/mies., Marża %) z kwotami; `:529` `lg:grid-cols-2`.
- 375 px: ucięte „Marża/mies.” i „Marża %”. 1024 px (lg, kolumna ~430 px) i ~1280 px z rozwiniętym sidebarem (~470 px): kwoty „125 430,00 zł” × 2 + nazwa nie mieszczą się → ucięte bez scrolla.
- **Naprawa:** `overflow-x-auto` na wrapperze; siatka `xl:grid-cols-2` zamiast `lg:`; `whitespace-nowrap` tylko na kwotach, nazwa `max-w-[12rem] truncate`.

### P1-12. Skrzynka zamówień — pasek zakładek bez zawijania
- `src/components/order-mail/OrderMailQueue.tsx:405` `mt-4 flex gap-2` (4 przyciski: „Do weryfikacji”, „Zapisane automatycznie (N)”, „Zapisane ręcznie”, „Nierozpoznane”).
- Na 375 px suma min-content ~435 px > 343 → etykiety łamią się, a pasek i tak przepełnia stronę.
- **Naprawa:** `mt-4 flex gap-2 overflow-x-auto` + przyciski `shrink-0 whitespace-nowrap` (albo `flex-wrap`).

### P1-13. Skrzynka zamówień — szczegół dokumentu pojawia się pod całą listą (< 1024 px)
- `OrderMailQueue.tsx:430` `grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]`: poniżej `lg` lista i `Detail` są w jednej kolumnie; `onSelect` (`:435`) nie przewija. Na telefonie i tablecie klik w pozycję listy „nic nie robi” — szczegół (z przyciskiem „Zastosuj”) ląduje pod kilkunastoma pozycjami.
- **Naprawa:** po `onSelect` < `lg` `document.getElementById("order-mail-detail")?.scrollIntoView({behavior:"smooth"})`, albo < `lg` szczegół w `Sheet` (pełny ekran) z przyciskiem „Wróć do listy”.

### P1-14. Rejestr kontraktów — picker klienta `min-w-[260px]` przepełnia 375 px
- `src/components/contracts/ContractsClientPicker.tsx:49-58`: kontener `px-3` + etykieta „KLIENT” (`tracking-[0.18em]`, `shrink-0`) + przycisk `min-w-[260px]` → ~10–15 px poziomego scrolla całej strony `/contracts`; tekst „Wszyscy klienci (lista globalna)” nie ucina się, bo `span.truncate` nie ma `min-w-0`.
- **Naprawa:** przycisk `min-w-0 flex-1 sm:min-w-[260px] sm:flex-none`, span `min-w-0 truncate`; `PopoverContent className="w-[min(320px,calc(100vw-2rem))]"`.

### P1-15. Harmonogram stawki kandydata — trzy pola w jednym wierszu flex
- `src/components/contracts/CandidateRateScheduleFields.tsx:60-100` `flex items-end gap-2` z trzema `flex-1` (stawka + 2 × `type="date"`) + przycisk 36 px. Używane w `/contracts/[id]` (edycja), `/contracts/new`, `AddProjectDialog`.
- Na 375 px (w karcie p-6) każde pole ~70 px → daty nieczytelne; etykiety tylko w pierwszym wierszu, więc po zawinięciu wyrównanie znika.
- **Naprawa:** `grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end`; etykiety widoczne w każdym wierszu < `sm` (`sm:hidden` dla powtórek zamiast `idx === 0`).

### P1-16. Generator CV — wiersz „Wygenerowane CV”: klaster akcji `shrink-0` zjada nazwisko
- `src/components/v2/pages/CVGeneratorStandaloneV2.tsx:2122` `flex items-center justify-between gap-3` + `:2201` `flex shrink-0 items-center gap-1` z przyciskami: „Użyj w rekrutacji” / „Wybrano · wczytaj ponownie” (~130–200 px) + 4–5 ikon `size="sm"` (~40 px) + „Wygeneruj ponownie” / kosz.
- Na 375 px (treść ~295 px wewnątrz `container max-w-3xl` + Card) klaster ma 300–380 px → kolumna z nazwiskiem (`min-w-0`) spada do 0 px, a akcje wystają poza kartę.
- **Naprawa:** `flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between`; klaster `flex flex-wrap items-center gap-1 sm:shrink-0`; ikony z `aria-label` (dziś tylko `title`).

### P1-17. Generator CV — podgląd DOCX: „Pobierz” pod przyciskiem zamknięcia
- `CVGeneratorStandaloneV2.tsx:2354-2365`: `DialogHeader className="flex-row … px-4 py-3"` — `px-4` (twMerge) kasuje bazowe `pr-16` z `ui/dialog.tsx:89`, więc przycisk „Pobierz” stoi przy prawej krawędzi dokładnie pod `DialogPrimitive.Close` (`absolute right-4 top-4 h-11 w-11`). Na każdej szerokości X przykrywa „Pobierz” (klik zamyka okno zamiast pobierać).
- **Naprawa:** `DialogHeader className="flex-row items-center justify-between gap-3 border-b py-3 pl-4 pr-16"`.
- Dodatkowo (P2): `docx-preview` renderuje strony o stałej szerokości A4 (~794 px) — na telefonie tylko poziomy scroll, bez dopasowania do szerokości (`transform: scale()` hosta wg `clientWidth / 794`).

### P1-18. Edytor brandowanego CV — plakietka statusu pod przyciskiem zamknięcia
- `src/components/v2/modals/CVBrandedEditModal.tsx:383, 425, 444-455`: `DialogContent … p-0`, nagłówek `flex … justify-between px-5 py-3`, po prawej plakietka „Sfinalizowane”/„Szkic vN” — pod `Close` (`right-4 top-4`, 44 px). Gdy nie ma banerów nad nagłówkiem (typowy przypadek), X zakrywa plakietkę.
- **Naprawa:** nagłówek `pl-5 pr-16`.

### P1-19. Kontraktorzy („Obsługa kontraktorów”) — podwójny padding
- `src/components/v2/pages/ContractorsListV2.tsx:233` `max-w-[1400px] mx-auto space-y-4 p-6` renderowane wewnątrz `/contracts` (`src/app/contracts/page.tsx:207`), który już jest w shellowym `p-4 md:p-6` → na 375 px 40 px marginesu z każdej strony, treść 295 px; tabela 9-kolumnowa (`:309-323`) i tak przewija się w poziomie, a baner „draft czeka…” (`:249`) z przyciskiem łamie się ciasno.
- **Naprawa:** usunąć `p-6` (rejestr `ContractsListV2` go nie ma — spójność).

### P1-20 → faktycznie P2 (na granicy). `/contracts` rejestr klienta — wiersz filtrów z datami na sztywno
- `src/components/contracts/ClientContractRegister.tsx:575-606`: grupa `flex items-center gap-1.5` z dwoma `Input type="date" className="h-9 w-[150px]"` (~316 px, bez zawijania) + `MultiSelectFilter` `w-[170px]`/`w-[190px]`. Na 375 px grupa dat zajmuje 92% szerokości i wraz z `FilterBar` mieści się na granicy — przy włączonym `min-w-48` wyszukiwania i przycisku „Eksportuj do Excela” w `actions` powstaje przepełnienie.
- **Naprawa:** grupa dat `grid grid-cols-[1fr_auto_1fr] w-full sm:flex sm:w-auto`, inputy `w-full sm:w-[150px]`; triggery filtrów `w-full sm:w-[170px]`.

---

## P2

1. **Kontrakt — pasek 9 zakładek bez `whitespace-nowrap`** — `src/app/contracts/[id]/page.tsx:1129-1147`: `overflow-x-auto` jest (dobrze), ale przyciski bez `shrink-0 whitespace-nowrap`, więc „Notatki / Rozmowy”, „Historia stawek” łamią się na 2 linie; brak wskazówki, że pasek się przewija. Naprawa: `shrink-0 whitespace-nowrap` + maska gradientu na krawędzi.
2. **Rejestr kontraktów — akcje nagłówka bez zawijania** — `src/components/v2/pages/ContractsListV2.tsx:788` `flex items-center gap-2` (Analityka + Eksport + Nowy kontrakt ≈ 340 px przy 343 px). Naprawa: `flex flex-wrap items-center gap-2`.
3. **Benchmark stawki** — `src/components/contracts/ContractRateBenchmarkCard.tsx:55` `grid grid-cols-3 gap-4` bez breakpointu: na 375 px ~85 px na kolumnę, kwota + procent różnicy łamią się. Naprawa: `grid grid-cols-1 gap-3 sm:grid-cols-3`.
4. **„Dodaj kolejny projekt” — 5 kolumn w oknie 672 px** — `src/components/contracts/AddProjectDialog.tsx:570` `sm:grid-cols-2 lg:grid-cols-5` w `AppModal size="lg"` (`max-w-2xl`): od 1024 px kolumny ~112 px, etykieta „Waluta przychodowa (klienta)” w 3 liniach, pola rozjechane. Naprawa: zostawić `sm:grid-cols-2` (bez `lg:grid-cols-5`) albo `size="xl"`.
5. **Formularze edycji w siatce 2-kolumnowej od 0 px** — `src/app/contracts/[id]/page.tsx:1966, 2014`, `ContractAmendmentsTab.tsx:287`, `ContractEquipmentTab.tsx:297`, `CvGeneratedShareModal.tsx:202`: `grid grid-cols-2` na 375 px daje pola ~140 px (liczbowe/daty ciasne). Naprawa: `grid grid-cols-1 gap-3 sm:grid-cols-2`.
6. **Skrzynka zamówień — szczegół** — `OrderMailQueue.tsx:641-645`: temat/nadawca/nazwa załącznika bez `min-w-0 break-words` (długie nazwy PDF bez spacji wypychają przycisk „PDF”); `:672` `dl grid grid-cols-2 gap-x-6`; `:678` tabela 4-kolumnowa bez wrappera `overflow-x-auto`. Naprawa: `min-w-0 break-words` na kolumnie tekstu, `[overflow-wrap:anywhere]` na nazwie pliku, tabela w `overflow-x-auto`.
7. **Rejestr klienta / Kontraktorzy — tabele bez widoku kart na telefonie** — `ClientContractRegister.tsx:646` (8 kolumn), `ContractorsListV2.tsx:309` (9 kolumn): działa poziomy scroll (`ui/table.tsx:27` `overflow-auto`), ale kolumna akcji („Aktywuj/Uzupełnij”) jest ostatnia i niewidoczna bez przewinięcia. Naprawa: wzorzec kart z `ContractsListV2` (`max-xl:block`) albo `md:` ukrywanie mniej ważnych kolumn.
8. **Kontraktorzy — zakładki** — `ContractorsListV2.tsx:268-300`: `flex gap-1` bez `overflow-x-auto`; „Aktywni 120 osób / 150 umów” łamie się w kilku liniach. Naprawa: `overflow-x-auto` + `whitespace-nowrap`.
9. **Cele dotykowe < 40 px** — ikony akcji B2B `h-8 w-8` (`B2BContractGeneratorV2.tsx:2404-2470`), filtr daty w nagłówku kolumny `rounded p-0.5` z ikoną 14 px ≈ 18 px (`:1152-1159`), zamknięcie panelu UoP `h-6 w-6` bez `aria-label` (`:4101-4108`), ikony wiersza CV `size="sm"` (`CVGeneratorStandaloneV2.tsx:2219-2280`), wysyłka czatu `h-9 w-9` (`/cv/i` `page.tsx:646`). Naprawa: `h-10 w-10 md:h-8 md:w-8`; filtr daty `p-2 -m-1.5`.
10. **iOS zoom na polach (globalnie, dotkliwe na stronach publicznych)** — `ui/input.tsx:19`, `ui/select.tsx:19`, `ui/textarea.tsx:16`, `globals.css:541-551` (`text-sm`); dodatkowo `h-8 text-xs` w filtrach dat B2B (`:1178, :1192`). Publiczne: `/engagement/[token]/page.tsx:199` (textarea), `/cv/i` czat `page.tsx:641`. Naprawa: `text-base md:text-sm` w prymitywach i regule `globals.css`.
11. **Okna na 375 px dotykają krawędzi** — `ui/dialog.tsx:59` `w-full`. Naprawa: `w-[calc(100%-1.5rem)] sm:w-full`.
12. **`/cv/i` — wysokość ramki mierzona raz** — `page.tsx:673-677, 876-878`: `fitCvFrame` tylko w `onLoad`; obrót telefonu/zmiana szerokości zmienia wysokość treści → ucięcie dołu albo pusta przestrzeń. Naprawa: `ResizeObserver` na `contentDocument.documentElement` albo `resize` listener wywołujący `fitCvFrame`.
13. **`/cv/i` — czat i kafelki wymagań pod całym CV na telefonie** — `page.tsx:860-883`: < `lg` czat ląduje pod iframe o wysokości całego CV (min 600 px), klient z telefonu go nie znajdzie. Dziś funkcja wyłączona flagą `CV_INTERACTIVE_ENABLED=false`, stąd P2. Naprawa przy włączeniu: < `lg` pływający przycisk „Zapytaj o kandydata” otwierający czat w `Sheet`.
14. **`/sign/[token]` — podgląd PDF w `<iframe>`** — `SignForm.tsx:197-201` `w-full h-[460px]`: iOS Safari pokazuje tylko 1. stronę, Chrome na Androidzie nie renderuje PDF w ramce (pusto / pobieranie). Moduł podpisu jest wyłączony na produkcji (`SIGNING_ENABLED=false`), stąd P2. Naprawa: < `md` ukryć ramkę i pokazać duży przycisk „Otwórz umowę (PDF)”, albo użyć istniejącego `SearchablePdfPreview` (pdf.js).
15. **B2B — inline edycja klienta w wierszu** — `B2BContractGeneratorV2.tsx:2223` `h-8 min-w-[16rem]` rozszerza tabelę o 256 px w trakcie edycji (akcje przyklejone przykrywają pole na tablecie). Naprawa: `min-w-[12rem] md:min-w-[16rem]`.
16. **B2B — podgląd umowy** — `:4029-4043` `CardHeader flex-row … justify-between` bez `flex-wrap` (tytuł + „Drukuj / PDF” na 295 px ciasno) i `iframe h-[520px]` — na telefonie OK, na 1920 px mały. Naprawa: `flex-wrap gap-2`; `h-[60vh] min-h-[420px]`.
17. **Generator CV — przełączniki opcji** — `CVGeneratorStandaloneV2.tsx:1254, 1265` `flex items-center justify-between gap-4`, kolumna tekstu bez `min-w-0` — długie opisy przy wąskim ekranie OK (zawijają się), ale `Switch` może się ścisnąć. Naprawa: `min-w-0 flex-1` na opisie, `shrink-0` na `Switch`.

---

## Co jest zrobione dobrze

- **Rejestr kontraktów (`ContractsListV2.tsx:998-1370`)** — wzorcowo: poniżej `xl` tabela przechodzi w karty (`max-xl:block`, `max-xl:grid max-xl:grid-cols-2`, `MobileFieldLabel`), `table-fixed` + `colgroup` w %, `TruncatedText`, `min-w-0` na komórkach. Wyszukiwarka `min-w-[240px] flex-1` w `flex-wrap`, filtry w `Popover`.
- **Pasek akcji zbiorczych** (`v2/modals/ContractsBulkActionsBar.tsx:102`) — `max-w-[min(96vw,900px)]` + `flex-wrap`.
- **`WorkspaceModeTabs`** (`ds/WorkspaceModeTabs.tsx:34`) — `flex-wrap`, nie przepełnia.
- **Formularze** `/contracts/new` (`max-w-3xl`, `sm:grid-cols-2`, `lg:grid-cols-4`), Generator B2B (sekcje `sm:grid-cols-2`, popovery `w-(--radix-popover-trigger-width)`), `ContractRegisterDialog` (`sm:grid-cols-2`), `ContractCandidateContactRow` (`min-w-0`, `sm:grid-cols-2`), reguły CV (`sm:grid-cols-2`, `md:grid-cols-2`, `flex-wrap`).
- **Generator CV** — jedna kolumna `max-w-3xl`; kafelki źródła `grid gap-3 sm:grid-cols-2` (`CvSourceTiles.tsx:41`); przyklejony dolny pasek „Generuj” z `flex-wrap` i tekstem pomocniczym ukrytym na telefonie (`:1313-1316`); lista wygenerowanych z własnym `max-h-[30rem] overflow-y-auto`.
- **Okna (baza)** — `max-h-[90vh] overflow-hidden`, `DialogBody overflow-y-auto min-h-0`, stopka `flex-col-reverse sm:flex-row`, zamknięcie 44 × 44 px; dialogi B2B używają `DialogBody`/`DialogFooter` poprawnie.
- **Szczegóły kontraktu** — nagłówek `flex-wrap`, układ `grid-cols-1 lg:grid-cols-3`, zakładki z `overflow-x-auto`, `InfoRow` z `min-w-0`.
- **Analityka** — prognoza (`:272, :297` `overflow-x-auto` + `min-w-fit`) i heatmapa rola × klient (`:617-642` `overflow-x-auto` + `sticky left-0` pierwszej kolumny); KPI `grid-cols-1 sm:grid-cols-2 lg:grid-cols-4`.
- **Sprzęt** (`ContractEquipmentTab.tsx:162`) i **historia rechecku skrzynki** (`OrderMailQueue.tsx:247`) — tabele w `overflow-x-auto`.
- **`/cv/i`** — nagłówek `flex-col sm:flex-row`, `p-4 sm:p-6`, `CvDocument` `p-6 sm:p-8`, edukacja `sm:grid-cols-[140px_1fr]`, siatka z czatem `lg:grid-cols-[minmax(0,1fr)_360px]` z `min-w-0`, czat `max-h-[420px]` na telefonie; iframe dopasowuje wysokość do treści (`fitCvFrame`).
- **`/sign`, `/engagement`** — wąskie, jednokolumnowe (`max-w-2xl px-6`, `max-w-xl p-6`), cała etykieta checkboxa jako cel dotykowy.
