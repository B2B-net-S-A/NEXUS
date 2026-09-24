# Audyt responsywności — strony publiczne (08)

Zakres: `/login/**`, `/register/**`, `/auth/**`, `components/blocks/AuthShell`, `components/login4.tsx`,
strona kariery (`/kariera/**` + `components/career/**`), `/apply/[token]`, `/share/champion-card/[token]`,
`/sign/[token]`, `/cv/[token]`, `/cv/i/[token]`, `components/public/**`, `not-found.tsx`, `error.tsx`,
`global-error.tsx`, `app/layout.tsx`.

Metoda: statyczne czytanie kodu (bez uruchamiania serwera i przeglądarki). Szerokości docelowe: 360–390 px
(główne), 768 px, 1440 px. Breakpointy Tailwinda domyślne (`globals.css` `@theme` nie nadpisuje
`--breakpoint-*`). Ścieżki względem `frontend/`, chyba że zaznaczono `backend/`.

Wszystko oznaczone „niepotwierdzone” wymaga sprawdzenia w przeglądarce (iOS Safari / Chrome Android) —
wniosek wynika z kodu, nie ze zrzutu.

## Podsumowanie

| Waga | Liczba |
|---|---|
| P0 (nie do użycia na telefonie) | 1 (uśpione — funkcja wyłączona flagą) |
| P1 (zepsuty układ / przewijanie w bok / ukryta treść / zoom iOS) | 4 |
| P2 (kosmetyka, ergonomia) | 20 |

Najważniejsze: globalna reguła w `globals.css` wymusza 14 px na każdym polu tekstowym — iPhone powiększa
stronę przy każdym dotknięciu pola na logowaniu, rejestracji, resecie hasła i w formularzu `/apply`.
Strona kariery (najważniejsza publiczna powierzchnia) jest zrobiona dobrze i tej reguły unika.

---

## P0

### P0-1. Klasyczne CV pod `/cv/{token}` nieczytelne na telefonie (sztywna kolumna 230 px)
- **Plik:** `backend/app/services/cv_html_renderer.py:340` (`.cv-body { grid-template-columns: 230px 1fr }`),
  `:292` (`.cv-header` padding 32/40), `:333` (`.cv-header-date` `position:absolute; right:40px`);
  renderowane w `src/app/cv/[token]/page.tsx:135-140` (iframe `srcDoc`).
- **Co pada:** iframe ma szerokość kontenera (~326 px przy 360 px ekranu, `p-4`). Kolumna boczna zjada
  230 px, na główną treść (doświadczenie) zostaje ~96 px minus `padding: 28px 32px` → ~30 px tekstu, czyli
  jedno-dwa słowa w linii. Data w nagłówku (absolutna, `right:40px`) nachodzi na imię i nazwisko.
  Szablon ma tylko `@media print`, żadnego zapytania dla wąskiego ekranu. `meta viewport` w dokumencie
  iframe'a nic nie daje (iframe dziedziczy szerokość z rodzica).
- **Dlaczego „uśpione”:** tworzenie linków klienta jest wyłączone (`CV_CLIENT_LINKS_UI_ENABLED = false`,
  `src/lib/cv-generator.ts:23`), ale linki wydane wcześniej działają do wygaśnięcia, a po włączeniu flagi
  hiring manager otwierający link z maila na telefonie dostanie nieczytelny dokument.
- **Poprawka (backend, CSS szablonu):**
  ```css
  @media (max-width: 640px) {
    .cv-body { grid-template-columns: 1fr; }
    .cv-sidebar { border-right: 0; border-bottom: 1px solid #e2e8f0; padding: 20px 16px; }
    .cv-main { padding: 20px 16px; }
    .cv-header { padding: 24px 16px 20px; }
    .cv-header-date { position: static; margin-top: 8px; }
  }
  ```

---

## P1

### P1-1. Globalna reguła wymusza 14 px w polach → iOS powiększa stronę przy fokusie (systemowe)
- **Plik:** `src/app/globals.css:541-553` — w `@layer utilities`:
  `input[type="text"|"email"|"password"|"number"|"tel"|"url"|"date"|"datetime-local"], select, textarea { @apply text-sm; }`
  oraz `src/components/ui/input.tsx:19`, `textarea.tsx:16`, `select.tsx:19` (`text-sm` w bazowej klasie).
- **Co pada:** iOS Safari przy fokusie pola z `font-size < 16px` przybliża całą stronę i nie oddala po
  wyjściu z pola. Dotyczy wszystkich publicznych formularzy poza stroną kariery:
  - `/login` (`src/app/login/page.tsx:278-299`, e-mail + hasło, dodatkowo `autoFocus`),
  - `/register` (`src/app/register/page.tsx` pola imię/e-mail/hasło ×2),
  - `/login/forgot-password`, `/login/reset`,
  - `/apply/[token]` (patrz P1-2),
  - czat `/cv/i/[token]` (`src/app/cv/i/[token]/page.tsx:636-642`, `h-9 text-sm`; czat wyłączony flagą,
    więc tam P2).
- **Pułapka:** selektor atrybutowy `input[type="email"]` (0,1,1) ma wyższą specyficzność niż klasa
  `.text-base` (0,1,0) w tej samej warstwie, więc **dopisanie `text-base` do pojedynczego pola nie
  zadziała** — trzeba zmienić regułę globalną.
- **Waga:** P1 (formularz działa, ale strona „odjeżdża” i trzeba ją ręcznie oddalić; na logowaniu to
  pierwsze wrażenie). Strona kariery NIE jest dotknięta — `career.css` jest poza warstwami, więc
  `.kr-input { font-size: 16px }` wygrywa z warstwą `utilities`.
- **Poprawka:** w `globals.css` zamienić `@apply text-sm;` na `@apply text-base sm:text-sm;`
  (albo owinąć selektory w `:where(...)`, żeby klasa na polu mogła regułę nadpisać). W `ui/input.tsx`,
  `ui/textarea.tsx`, `ui/select.tsx`: `text-base sm:text-sm` zamiast `text-sm`. Zmiana jest globalna
  (dotyka też aplikacji wewnętrznej) — od `sm` wygląd bez zmian.

### P1-2. `/apply/[token]`: pola 14 px i ~36 px wysokości
- **Plik:** `src/app/apply/[token]/ApplyForm.tsx:370` (`inputClass = "... px-3 py-2 text-sm ..."`),
  użyte w polach imię, nazwisko, e-mail, telefon, LinkedIn, wiadomość (`:224-322`).
- **Co pada:** przy 360 px iOS przybliża na każdym polu (P1-1), a wysokość ~36 px (`py-2` + 20 px linii)
  jest poniżej 44 px celu dotykowego. Imię i nazwisko nie mają atrybutu `type`, więc globalna reguła ich
  nie łapie — ale klasa `text-sm` w `inputClass` robi to samo.
- **Poprawka:** `inputClass`: `h-11 px-3 text-base sm:h-10 sm:text-sm` (dla `textarea` bez `h-11`,
  `py-2.5 text-base sm:text-sm`). Przy polu LinkedIn dodać `autoComplete="url"`, przy telefonie
  `inputMode="tel"` (typ `tel` już jest).

### P1-3. `/apply/[token]`: długa nazwa pliku CV rozpycha kartę → przewijanie w bok
- **Plik:** `src/app/apply/[token]/ApplyForm.tsx:283-292`.
  `<label className="flex items-center justify-between gap-3 ...">` → `<span className="inline-flex items-center gap-2 text-sm">{cvName ?? "Wybierz plik…"}</span>`.
- **Co pada:** nazwy plików CV zwykle nie mają spacji (`CV_Jan_Kowalski_Senior_Java_Developer_2026.pdf`,
  ~46 znaków × ~7,5 px ≈ 345 px). Element flex ma `min-width: auto` = szerokość najdłuższego
  niełamliwego słowa, a karta przy 360 px ma ~264 px wnętrza (`px-6` strony + `p-6` karty). Brak
  `min-w-0`/`truncate`/`break-all` → pole wychodzi poza kartę, strona przewija się w bok.
- **Poprawka:**
  ```tsx
  <span className="inline-flex min-w-0 flex-1 items-center gap-2 text-sm">
    <Paperclip className="h-4 w-4 shrink-0 text-muted-foreground" />
    <span className="truncate">{cvName ?? "Wybierz plik…"}</span>
  </span>
  <span className="shrink-0 text-xs text-muted-foreground">…</span>
  ```
  Na etykiecie dodać `min-h-11 focus-within:ring-2 focus-within:ring-primary/30` (plik jest `sr-only`,
  więc bez tego fokus klawiatury jest niewidoczny).

### P1-4. `/apply/[token]`: tytuł rekrutacji bez łamania słów (ryzyko przewijania w bok)
- **Plik:** `src/app/apply/[token]/page.tsx:104` — `h1 text-3xl md:text-4xl font-extrabold` bez
  `break-words`.
- **Co pada:** przy 360 px szerokość treści to 312 px; 30 px `extrabold` mieści ~17–18 znaków. Tytuły IT
  w formie „Programista/Programistka”, „DevOps/Infrastructure”, „Konsultant/Konsultantka SAP” to 21–24
  znaki bez spacji. Czy przeglądarka złamie po `/` — niepotwierdzone (zachowanie różni się między
  silnikami); jeśli nie, nagłówek wystaje poza ekran.
- **Poprawka:** `text-2xl sm:text-3xl md:text-4xl break-words hyphens-auto` (element ma `lang="pl"`
  z `<html>`, więc dzielenie słów działa po polsku). Ta sama klasa przyda się na `h1` imienia i nazwiska
  w `share/champion-card/[token]/page.tsx:176` (`text-4xl` na 360 px — nazwiska dwuczłonowe mają
  myślnik, więc tam ryzyko mniejsze).

---

## P2

### Logowanie, rejestracja, AuthShell
1. **`min-h-screen` = `100vh`** — `src/components/blocks/AuthShell.tsx:33`. Na iOS/Android `100vh` to
   wysokość bez paska adresu, więc wycentrowana karta ląduje niżej niż środek widocznego ekranu i pojawia
   się zbędne przewijanie. Poprawka: `min-h-svh` (albo `min-h-dvh`), z `min-h-screen` jako fallbackiem.
   To samo w `login/page.tsx:382`, `login/microsoft/callback/page.tsx:101,127`, `apply/layout.tsx:12`,
   `sign/layout.tsx:13`, `cv/layout.tsx:12`, share `champion-card/[token]/page.tsx:~140`.
2. **Przycisk „pokaż hasło” ma cel dotykowy 16×16 px, a tekst pola wchodzi pod ikonę** —
   `src/app/register/page.tsx:248-255`, `src/app/login/reset/page.tsx:137-144`. Przycisk to goła ikona
   `h-4 w-4` na `absolute right-3`, a `Input` nie dostaje `pr-10`. Poprawka: przycisk
   `absolute right-1 top-1/2 -translate-y-1/2 inline-flex h-10 w-10 items-center justify-center rounded-md`,
   pole `className="pr-11"`.
3. **Przyciski 40 px** — `src/components/ui/button.tsx:30` (`lg: "h-10 ..."`) używane jako główne CTA
   logowania/rejestracji; przycisk SSO `py-2.5` (~40 px, `login/page.tsx:339`). Poprawka na stronach
   auth: `className="w-full h-11 sm:h-10"`.
4. **Małe linki tekstowe** („Zapomniałeś hasła?”, „Zarejestruj się”, „Wróć do logowania”) —
   `login/page.tsx:307-313`, `register/page.tsx:277-283` itd. Wysokość ~20 px. Poprawka:
   `inline-flex min-h-11 items-center` na linkach.
5. **Długi e-mail w potwierdzeniu** — `login/forgot-password/page.tsx:50`
   (`<strong>{email}</strong>` bez łamania). Długi adres bez spacji może wyjść poza kartę 280 px.
   Poprawka: `className="break-all text-foreground"`.

### Strona kariery (`/kariera`, `kariera.dynaminds.pl`)
6. **`.kr-root { min-height: 100vh }`** — `src/components/career/career.css:30`. Na krótkich stronach
   (zamknięta rekrutacja, podziękowanie, 404) stopka (`margin-top:auto`) ląduje pod dolnym paskiem
   przeglądarki. Poprawka: `min-height: 100vh; min-height: 100svh;`.
7. **Brak `themeColor` i jasne tło `body` pod czarną stroną** — `src/app/kariera/layout.tsx` nie
   eksportuje `viewport`, root `layout.tsx:122` ma `body.bg-background` (jasne). Na iOS przy
   „przeciągnięciu poza stronę” widać jasny pas, a pasek Safari/Chrome nie przyjmuje czerni.
   Poprawka w `kariera/layout.tsx`:
   `export const viewport: Viewport = { themeColor: "#000000", colorScheme: "dark" };`
   i `html:has(.kr-root), html:has(.kr-root) body { background: #000 }` w `career.css`.
8. **Tytuł 46 px łamie słowa w środku** — `career.css:153-161` (`.kr-title` 46 px, `overflow-wrap:
   break-word`; `.kr-hero` ma `anywhere`). Przy 360 px mieści się ~12 znaków Geist 800, więc
   „Infrastruktury”, „Programistka”, „Architektka” łamią się bez dywizu („Infrastruktur|y”). Nie ma
   przewijania w bok, ale wygląda na błąd. Poprawka: `font-size: clamp(34px, 11.5vw, 46px);
   hyphens: auto;` (`.kr-root` ma `lang="pl"`).
9. **Proces rekrutacji i manifest schowane na telefonie** — `CareerJobView.tsx:116-126`
   (`.kr-desktop-only`, `career.css:307`). Kandydat na telefonie (główny ruch z LinkedIna) nie widzi
   kroków procesu. Jeśli to decyzja z makiety 390 px — w porządku; jeśli nie, `ProcessSteps` ma już
   siatkę 2×2 (`.kr-steps`) i zmieści się na telefonie.
10. **768–1023 px: tekst na pełną szerokość** — `.kr-main`/`.kr-col` (`career.css:242-253`) nie ma
    `max-width` poniżej 1024 px, więc na tablecie pionowo akapity mono 14 px mają ~90 znaków w linii, a
    formularz (1 kolumna) rozciąga się na 744 px. Poprawka:
    `@media (min-width: 640px) and (max-width: 1023px) { .kr-top, .kr-main { max-width: 720px; margin-inline: auto; } }`.
11. **Stopka bez łamania długiego adresu** — `CareerFooter.tsx:19` (`{hostLabel}` np.
    `kariera.dynaminds.pl/r/senior-java-developer-…`), `.kr-footer` (`career.css:678`) nie ma
    `overflow-wrap`. Poprawka: `.kr-footer { overflow-wrap: anywhere; }`. Link `klauzula_rodo` ma 11 px
    i ~18 px wysokości — `display:inline-block; padding:12px 0` dla celu dotykowego.
12. **`input[type=date]` z `appearance: none` na iOS** — `career.css:386` + `CareerApplyForm.tsx:464-473`.
    iOS Safari przy `appearance:none` pokazuje puste pole bez wzorca daty (niepotwierdzone). Poprawka:
    `input[type="date"].kr-input { -webkit-appearance: auto; appearance: auto; min-width: 0; }`
    albo `placeholder`-owy napis obok etykiety.
13. **Wiersz parametrów bez `min-width: 0`** — `.kr-kv-row` (`career.css:189-196`). Wartość z długim
    tokenem (np. link, e-mail) rozepchnie wiersz. Poprawka: `.kr-kv-row > * { min-width: 0;
    overflow-wrap: anywhere; }`.

### `/apply/[token]`, `/share`, `/sign`
14. **Podwójny padding na telefonie** — `apply/[token]/page.tsx:83` (`px-6`) + `:130` (`p-6`) → 264 px
    wnętrza przy 360 px; tak samo share `champion-card/[token]/page.tsx:146,203,207,235` i
    `sign/[token]/page.tsx:74` + karty `p-5`. Poprawka: `px-4 sm:px-6`, karty `p-4 sm:p-6 md:p-8`.
15. **Stopki `justify-between` bez zawijania** — `apply/[token]/page.tsx:134`,
    `share/champion-card/[token]/page.tsx:304`. Na 360 px dwa napisy ściskają się w kolumny po 2–3 słowa.
    Poprawka: `flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between`.
16. **Nagłówek share ściśnięty** — `share/champion-card/[token]/page.tsx:146` (logo + „NEXUS ·
    DYNAMINDS” ~214 px i „Ważne do …” ~136 px na 312 px). Poprawka: `flex-wrap gap-2`.
17. **`/apply`: po błędzie walidacji brak przewinięcia do pierwszego błędnego pola** —
    `ApplyForm.tsx:180-195`. Na telefonie błąd przy „Imię” jest nad krawędzią ekranu, widać tylko baner
    przy przycisku. Poprawka: po `setErrors` `form.querySelector('[aria-invalid="true"]')?.focus()` i
    `aria-invalid`/`aria-describedby` na polach (dziś tylko zgoda ma `aria-invalid`). Strona kariery robi
    to dobrze (fokus na podsumowaniu błędów).
18. **`/sign`: podgląd PDF w `<iframe>` 460 px** — `sign/[token]/SignForm.tsx:197-201`. Chrome Android
    nie renderuje PDF w iframe (pusta ramka lub pobieranie), iOS pokazuje tylko pierwszą stronę bez
    przewijania. Moduł podpisu jest wyłączony na produkcji (`SIGNING_ENABLED=false`), stąd P2. Poprawka:
    poniżej `md` ukryć iframe (`hidden md:block`) i zostawić przycisk „Pobierz PDF” jako główną akcję.

### Publiczne CV
19. **`/cv/{token}`: przewijanie w przewijaniu** — `cv/[token]/page.tsx:139`
    (`height: calc(100vh - 220px); minHeight: 600`). Na telefonie iframe jest wyższy niż ekran, a sam też
    się przewija — palec „utyka” w CV. Poprawka: dopasować wysokość do treści jak w `/cv/i`
    (`onLoad` → `contentDocument.documentElement.scrollHeight`), albo `h-[70svh]`.
20. **`/cv/i/{token}`: wysokość ramki liczona raz** — `cv/i/[token]/page.tsx:673-677` (`fitCvFrame`
    tylko przy `onLoad`). Obrót telefonu zmienia szerokość, treść się przelewa, ramka zostaje ze starą
    wysokością (ucięty dół albo pusta przestrzeń). Poprawka: `ResizeObserver` na
    `contentDocument.body` albo nasłuch `resize` wołający `fitCvFrame`. Dodatkowo szablon
    `backend/app/services/cv_generator_b2b/html_export.py:345` (`.cv { padding: 34px 40px }`) i `:356`
    (`.edu-dates { flex: 0 0 92px }`) daje ~210 px tekstu przy 360 px — dodać
    `@media (max-width: 600px) { body { padding: 8px } .cv { padding: 20px 16px } .edu { flex-direction: column; gap: 0 } .job-head { flex-wrap: wrap } }`.

### Strony błędów i układ główny
- (w liczniku jako część pkt 1 i 7) **`global-error.tsx`** renderuje własne `<html>` bez `<head>`/`meta
  viewport` — czy Next wstrzykuje domyślny viewport w tej ścieżce: niepotwierdzone. Jeśli nie, telefon
  pokaże stronę w szerokości 980 px (drobny tekst). Poprawka: `<head><meta name="viewport"
  content="width=device-width, initial-scale=1" /></head>`.
- **`not-found.tsx:19`** — „404” w `text-[9rem]` (~260–300 px) mieści się na 360 px na styk; przycisk
  „Wróć do dashboardu” (`:37-44`, `h-10`) prowadzi obcą osobę do logowania. Kosmetyka:
  `text-[6rem] sm:text-[9rem]`, `h-11`.
- **Szkielet dashboardu na stronach publicznych** — `src/app/loading.tsx` (siatka kart + tabela) jest
  granicą Suspense nad wszystkimi segmentami, a `/kariera`, `/apply`, `/share`, `/sign`, `/cv` nie mają
  własnego `loading.tsx`. Kandydat otwierający `force-dynamic` stronę rekrutacji może na chwilę zobaczyć
  jasny szkielet pulpitu przed czarną stroną kariery (niepotwierdzone w przeglądarce). Poprawka:
  `src/app/kariera/loading.tsx` z samym `TerminalChrome`/czarnym tłem (i proste `loading.tsx` dla
  pozostałych publicznych segmentów).

---

## Co jest zrobione dobrze

- **Zoom nie jest zablokowany.** Root `layout.tsx` nie eksportuje `viewport`, więc Next daje domyślne
  `width=device-width, initial-scale=1` — bez `maximum-scale=1` / `user-scalable=no`. `lang="pl"` na
  `<html>`.
- **AuthShell** (`blocks/AuthShell.tsx`) — panel marki tylko od `lg` (`hidden lg:flex`), na telefonie
  logo nad nagłówkiem, `px-4`, `max-w-sm w-full`. Na 768 px jedna kolumna, na 1440 px podział 50/50.
  Poprawne `autoComplete` (`email`, `current-password`, `new-password`, `name`) i typy pól.
- **Strona kariery** to wzorzec dla reszty:
  - CSS pisany mobile-first (układ 390 px, desktop od 1024, pełne marginesy od 1280), siatki
    `minmax(0, 1fr)`, `overflow-wrap: anywhere` na hero, komunikatach i polu pliku;
  - pola 16 px i 48 px wysokości (brak zoomu iOS), przycisk wysyłki 52 px, rozwijane „opcjonalnie” 44 px,
    link pomocniczy 44 px, wiersze listy rekrutacji 44 px, checkbox zgody 22 px z klikalną całą etykietą;
  - `type="email"` + `inputMode="email"`, `inputMode="decimal"` na stawce, `autoComplete` given-name /
    family-name / email / address-level2;
  - pole pliku: przezroczysty `input` na całej etykiecie (dotyk otwiera wybór pliku), `accept` z MIME
    (iOS proponuje „Pliki”), osobny opis „dodaj plik z telefonu”;
  - brak elementów `sticky`/`fixed` zasłaniających treść; przycisk „$ ./aplikuj — 2 min” przewija do
    formularza (`scroll-margin-top`);
  - błędy: podsumowanie z fokusem (przewija do góry formularza), komunikaty przy polach z
    `aria-describedby`, dane i plik zostają po błędzie, po wysłaniu `scrollTo(top)`;
  - plakietka „ENTER” chowana poniżej `sm`.
- **`/cv/i/{token}`** — `p-4 sm:p-6`, nagłówek `flex-col sm:flex-row`, czat przyklejony tylko od `lg`,
  `max-h-[420px]` czatu na telefonie, kafelki wymagań z `truncate` i `min-w-0`, edukacja
  `sm:grid-cols-[140px_1fr]`, ramka CV dopasowuje wysokość do treści.
- **`/cv/{token}`** — nagłówek `flex-col sm:flex-row`, `p-4 sm:p-6`.
- **`/apply`** — `grid-cols-1 md:grid-cols-2` (jedna kolumna na telefonie), checkbox zgody `h-5 w-5`
  z klikalną etykietą, poprawne typy `email`/`tel`/`url`.
- **Grafiki OG** (`kariera/r/[slug]/opengraph-image.tsx`, `p/[slug]`, `career/og.tsx`) mają stały
  rozmiar 1200×630 i nie zależą od układu strony.
- `components/login4.tsx` jest używany wyłącznie w harnessie `/preview/login` — nie ma wpływu na produkcję.
- `/auth/microsoft/callback` to `route.ts` (handler bez UI).

## Znalezione poza zakresem responsywności

- **Brakujące spacje w tekście (widoczny błąd):** `{""}` zamiast `{" "}` —
  `share/champion-card/[token]/page.tsx:161` renderuje „Ważne do30.09.2026”, `:193` „Rekomendacja na
  stanowisko:Senior…”, `apply/[token]/page.tsx:116` ikona przyklejona do „Senior”. Wygląda na artefakt
  formatera.
- **`/engagement/[token]`** (publiczny, poza listą zakresu): `textarea` `text-sm` (zoom iOS) i podwójny
  padding `p-6` + `p-6` (`src/app/engagement/[token]/page.tsx:151-152,199`).
- `share/champion-card/[token]/page.tsx:~140` — tło „ambient glow” ma nieprawidłowe CSS
  (`hsl(var(--primary))/15` wewnątrz `radial-gradient`), więc gradient się nie renderuje.
- `/apply` — zagnieżdżone `<label>` (pole CV w `Field` jest etykietą w etykiecie,
  `ApplyForm.tsx:283` wewnątrz `Field` `:375`) — niepoprawny HTML, działa przypadkiem.
