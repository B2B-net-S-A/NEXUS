# Tailwind CSS 3.4.19 → 4.3.3 — ocena i wykonanie migracji

> Data: 2026-07-27 · Branch: `deps/tailwind-4-assessment` · Werdykt: **WYKONANE**
> Zakres: `frontend/` (Next.js 15.1, React 19). Dependabot PR #53 (2026-04-21) — nieaktualny, nie użyty.

**Uwaga o wersji:** zlecono 4.2.4, zainstalowano **4.3.3** — to bieżący `latest` w npm
i wersja, którą wybiera oficjalny kodmod. Cofanie do 4.2.4 nie ma uzasadnienia.

---

## 1. Werdykt

Migracja jest wykonalna i została wykonana, **ale oficjalny kodmod sam z siebie daje
wynik zepsuty w sposób, którego zielony build nie wykrywa**. Wymagał 4 ręcznych korekt
(§4). Po nich: type-check czysty, lint bit-w-bit identyczny z baseline, build zielony,
728/728 testów, a różnica wizualna na realnych ekranach to **maks. 2–6/255 na kanał**
(poziom antyaliasingu, zero przepływu tekstu).

Kluczowy wniosek dla systemu designu: **wartości tokenów w ogóle się nie ruszają**.
193 deklaracje custom properties w `globals.css` zostają nietknięte; zmienia się tylko
warstwa, która mapuje je na utilities (`tailwind.config.ts` → `@theme inline`).

---

## 2. Inwentaryzacja (stan przed)

### System tokenów — `src/app/globals.css` (593 linie)

| miara | wartość |
|---|---|
| deklaracji custom properties | **225** |
| unikalnych nazw tokenów | **50** |
| zakresów motywu (bloków selektorów) | **18** |
| palet akcentu | **7** (indigo domyślne + violet/blue/green/orange/rose/graphite) |
| ortogonalnych osi motywu | 3 (`.dark`, `[data-soft]`, `[data-kids]`) |
| kombinacji motywu | **56** (7 × dark × soft × kids) |
| nieulayerowanych selektorów dekoracyjnych (Soft/Kids) | 34 |

Rozkład deklaracji: `:root` 48 · `.dark` 44 · 12 bloków palet po 3 · `html[data-soft]` 4 ·
`html.dark[data-soft]` 5 · `html[data-kids]` 47 · `html.dark[data-kids]` 44.

**Wszystkie 18 zakresów siedzi na `<html>`** — to fakt, od którego zależy poprawność
migracji (§4.3).

### `tailwind.config.ts` (130 linii)

- `darkMode: "class"`, 3 globy `content`
- `theme.extend.colors` — 23 rodziny tokenów, wszystkie w formacie `hsl(var(--x))`,
  w tym 5-stopniowa rampa `chart-1..5` i 7 kluczy `sidebar.*`
- `fontFamily` (sans/display), `borderRadius` (lg/md/sm z `--radius`),
  `letterSpacing` (4 własne), `keyframes` (3), `animation` (3)
- `plugins: [require("@tailwindcss/typography")]`
- **brak** `safelist`, `corePlugins`, `separator` → nic z listy „nieobsługiwane w v4"

### Zgodność pluginów (sprawdzone w npm, nie zgadywane)

| plugin | wersja w repo | latest | peerDependencies | werdykt |
|---|---|---|---|---|
| `@tailwindcss/typography` | ^0.5.15 | 0.5.20 | `>=3.0.0 \|\| >=4.0.0` | ✅ zgodny z v4 |
| `tailwindcss-animate` | — | — | — | **nieużywany** |
| `autoprefixer` | ^10.4.20 | — | — | usuwany (v4 ma wbudowany) |

### Powierzchnia zmian w kodzie (580 plików `.ts`/`.tsx`)

| wzorzec | wystąpień | charakter zmiany w v4 |
|---|---|---|
| `space-x-*` / `space-y-*` | **665** | zmiana selektora (`~` → `:not(:last-child)`) |
| modyfikatory przezroczystości na tokenach | **1054** | `hsl(x / a)` → `color-mix(in oklab, …)` |
| `rounded` (bez sufiksu) | 376 | przemianowane |
| `flex-shrink-0` | 159 | → `shrink-0` |
| `outline-none` | 158 | → `outline-hidden` (zmiana zachowania) |
| `shadow-sm` | **151** (78 plików) | **ta sama klasa, mniejsza wartość** |
| `bg-gradient-to-*` | 52 | → `bg-linear-to-*` |
| `ring-offset-*` | 20 | zachowane w v4 |
| `divide-gray-*` i inne surowe palety | ~290 | hex → oklch |
| `x-[--var]` | 10 | → `x-(--var)` |
| `@apply` poza `globals.css` | **0** | — (brak potrzeby `@reference`) |
| `theme()` w kodzie | **0** | — |

---

## 3. Wynik próby kodmodu (`npx @tailwindcss/upgrade`)

**222 pliki, +1392 / −1255.** Skasował `tailwind.config.ts`, przeniósł konfigurację do
`@theme` w `globals.css`, zmigrował `postcss.config.js`, usunął `autoprefixer`.

Poprawnie zrobił: przemianowania utilities (`shadow-sm`→`shadow-xs`, `outline-none`→
`outline-hidden`, `flex-shrink`→`shrink`, gradienty), `@custom-variant dark`, shim
`border-color` dla zmiany domyślnego koloru ramki, a także **43 podmiany wartości
arbitralnych na nazwane tokeny** (`tracking-[-0.01em]` → `tracking-heading`) — co jest
zgodne z zasadą token-first tego repo i daje identyczną wartość wyliczoną.

### Czego kodmod NIE zrobił / zepsuł

| # | defekt | wykrywalność | skala |
|---|---|---|---|
| 1 | **Zgubił plugin typography.** Skasował config z `plugins:[…]` i **nie dodał** `@plugin "@tailwindcss/typography"` | ⚠️ **cicha** — build zielony | 139 reguł `.prose` → **0**; 22 użycia `prose*` renderują się bez stylów |
| 2 | **Przepisał `variant="outline"` → `"outline-solid"`** w propsach komponentów (CVA), nie w klasach CSS | ✅ głośna — 31 błędów TS | 27 wystąpień / 17 plików, **100% false-positive** (w oryginale zero `outline` jako klasy CSS) |
| 3 | Użył `@theme` zamiast **`@theme inline`** | ⚠️ **cicha** | działa dziś tylko dlatego, że wszystkie 18 zakresów motywu jest na `<html>`; pierwszy zagnieżdżony motyw psuje palety |
| 4 | Nie przywrócił `button { cursor: pointer }` (usunięte z Preflight v4) | ⚠️ **cicha** | 757 `<button>`/`[role=button]`, tylko 99 z jawnym `cursor-pointer` → **~658 elementów** traci wskaźnik |
| 5 | Nie przywrócił koloru placeholdera (v3 `#9ca3af` → v4 `currentColor/50%`) | ⚠️ **cicha** | **346** inputów; w light mode placeholder robi się wyraźnie ciemniejszy |
| 6 | Zdegradował 4 klasy animacji z poziomu nieulayerowanego do `@layer utilities` | ⚠️ cicha | bez skutku (brak kolizji nazw), ale osłabia kaskadę |

Punkty 1, 4 i 5 to dokładnie ta klasa błędów, o którą chodzi w „zielony build nic tu
nie znaczy": aplikacja się kompiluje, testy przechodzą, a wygląda inaczej.

---

## 4. Zastosowane korekty

1. **`@plugin "@tailwindcss/typography";`** w `globals.css` → 80/80 selektorów `prose`
   wróciło (weryfikacja: `.prose` = 16px/28px w v3 i v4).
2. **`@theme` → `@theme inline`** → utilities emitują `background-color: hsl(var(--primary))`,
   **bajt w bajt jak v3**, i nadpisania tokenów działają w dowolnym węźle.
3. **Rewert 27 × `outline-solid` → `outline`** (potwierdzone: w oryginale `outline`
   występuje wyłącznie jako nazwa wariantu komponentu, nigdy jako klasa CSS).
4. **Shimy Preflight** w `@layer base`: `button:not(:disabled){cursor:pointer}` oraz
   `input/textarea::placeholder{color:#9ca3af}`.

Dodatkowo, poza samą migracją: `components.json` wskazywał na skasowany
`tailwind.config.ts` (naprawione na `"config": ""`), a `docs/ds/ADDING-BLOCKS.md`
opisywał workflow oparty na tym pliku (zaktualizowane + nowa sekcja o `@theme inline`).

---

## 5. Dowód braku regresji wizualnej

### 5.1 Poziom reguł CSS

Zbudowano v3 i v4 z **identycznej listy klas** i porównano wygenerowane deklaracje:
**46 klas identycznych, 6 różnych — wszystkie 6 to inny zapis tej samej wartości**
(`9999px` vs `calc(infinity*1px)`, `var(--radius-xl)` vs `0.75rem`, dodatkowa zmienna
`--tw-tracking` obok `letter-spacing`).

Kluczowe tokeny emitują się **znakowo identycznie**:
```
.bg-primary { background-color: hsl(var(--primary)); }   // v3 i v4
```

### 5.2 Modyfikatory przezroczystości (największe ryzyko teoretyczne — 1054 użycia)

v3 `hsl(var(--primary) / 0.1)` → v4 `color-mix(in oklab, hsl(var(--primary)) 10%, transparent)`.

Test: **21 realnych kolorów tokenów NEXUSa × 12 poziomów alfa = 252 kombinacje**,
wyrenderowane w Chromium na białym tle, porównane jako surowe piksele.

> **Hash PNG v3 == hash PNG v4 — renderowanie bit w bit identyczne.**

Powód: `color-mix` z `transparent` używa interpolacji z premultiplikowaną alfą, więc
przy jednym nieprzezroczystym składniku wynik to dokładnie ten kolor z zadaną alfą.

### 5.3 Macierz motywów — 56 kombinacji

Dla każdej z 7 palet × dark/light × soft × kids wyrenderowano 67 elementów pokrywających
wszystkie tokeny (kolory, radius, cienie, typografię, ramki, wykresy) i porównano piksele.

**64 z 67 elementów identyczne w każdej kombinacji.** Trzy różnice, wszystkie wyjaśnione:

| element | przyczyna | realna regresja? |
|---|---|---|
| `prose`, `prose-sm` | artefakt harnessu — nieulayerowana reguła testowa `.sw{font-size:9px}` bije `@layer`-owane `.prose` w v4. W izolacji: 16px/28px w obu | **nie** |
| `tracking-heading` | kodmod podmienił `tracking-[-0.01em]` → `tracking-heading`; obie emitują `letter-spacing:-0.01em` | **nie** |

### 5.4 Realne ekrany — zrzuty przed/po

`/login` i `/register` (publiczne, renderują się bez logowania), 1440×900, fullPage,
light i dark, `data-soft="true"`. Oba stany zbudowane produkcyjnie (`next build`) —
v3 z oryginalnego drzewa, v4 po migracji.

| ekran | pikseli różnych | **maks. delta kanału** | średnia delta |
|---|---|---|---|
| login light | 0.39 % | **2**/255 | 1 |
| login dark | 0.43 % | **2**/255 | 1 |
| register light | 0.42 % | **6**/255 | 1 |
| register dark | 0.69 % | **6**/255 | 1 |

Maks. delta 2–6/255 przy średniej 1 to poziom antyaliasingu. **Zero przepływu tekstu**
(reflow dałby deltę 255), zero przesunięć layoutu, zero zmian kolorów.

> Pułapka metodologiczna, na którą się nadziałem: pierwsze podejście dawało 2,1 %
> pikseli przy delcie 255 — bo skrypt ustawiał `documentElement.className = 'dark'`,
> kasując klasy zmiennych `next/font`. Bez `--font-inter` v3 spada do Times, a v4 do
> swojego stosu sans. Po poprawce na `classList.add` różnica znika. Warto pamiętać przy
> każdym przyszłym porównaniu wizualnym w tym repo.

### 5.5 Domyślna paleta (hex → oklch)

v4 przebudował paletę na oklch. Dotyczy ~290 pozostałości surowych palet
(`gray-*`, `slate-*`, `zinc-*` — istniejący dług DS, nie wprowadzony tą migracją).

Zmierzona różnica po konwersji do sRGB: **maks. 3/255 na kanale (~1,2 %)**,
w większości odcieni **0**. Niedostrzegalne.

### 5.6 Zmiana kaskady — v4 emituje prawdziwe `@layer`

v3 nie emitował żadnego `@layer`; v4 emituje 9 (`theme`, `base`, `components`, `utilities`).
Skutek: **każdy nieulayerowany CSS aplikacji bije teraz wszystkie utilities**, niezależnie
od specyficzności.

Dla NEXUSa to **zmiana korzystna**: 34 nieulayerowane selektory dekoracyjne Soft/Kids
(celowo napisane tak, „żeby biły klasy Tailwinda") wygrywają teraz przez warstwę zamiast
przez kolejność w pliku — czyli pewniej.

---

## 6. Weryfikacja

Zmierzone po rebase na `main` z recharts 3.x (#946), refaktorem `useClickOutside`
(#936) i usunięciem `@vitest/ui` (#945) — Tailwind 4 współistnieje z nimi bez zmian:

| krok | wynik |
|---|---|
| `npm run type-check` | ✅ czysty (przed korektą #2: 31 błędów) |
| `npm run lint` | ✅ **215 ostrzeżeń = baseline 215, pliki bit-w-bit identyczne, zero nowych** |
| `npm run build` | ✅ skompilowany, 87/87 stron statycznych |
| `npx vitest run` | ✅ **65 plików, 737/737 testów** |
| Dockerfile | ✅ `npm install --legacy-peer-deps` (devDeps dostępne), brak odwołań do `tailwind.config.ts` |

Pomiary wizualne (§5) wykonano przed rebase, na 63 plikach / 728 testach — dotyczą
warstwy CSS, której późniejsze commity na `main` nie ruszają.

### Konflikt rebase

Jedyny realny konflikt: `package.json` — `main` usunął `@vitest/ui`, ta gałąź usunęła
`autoprefixer`. Rozwiązanie: obie zależności usunięte. Wszystkie pliki `.tsx`
zmergowały się automatycznie.

---

## 7. Ryzyka rezydualne

1. **DS jest wspólny dla 4 aplikacji** (NEXUS/Compass/Atlas/ELEVATE). Po tym PR NEXUS
   jest pierwszy na v4 — `ADDING-BLOCKS.md` opisuje teraz oba światy, ale kod kopiowany
   z Compass/Atlas może zawierać klasy w składni v3 (`shadow-sm` o innym znaczeniu,
   `!flex` zamiast `flex!`). Do rozważenia: migracja pozostałych trzech w ślad za tym.
2. **Tailwind Plus** daje kod już w v4 — to po migracji **ułatwienie**, nie problem.
3. **`space-y-*` — jedyna realna, scharakteryzowana rozbieżność.** Zmiana selektora
   nie jest kosmetyczna: v3 nakłada `margin-top` na wszystkie dzieci poza pierwszym
   (`> :not([hidden]) ~ :not([hidden])`), v4 nakłada `margin-bottom` na wszystkie poza
   ostatnim (`> :not(:last-child)`).

   Przetestowano 6 scenariuszy w przeglądarce. **Odstęp między widocznymi elementami
   jest zawsze identyczny.** Różnica pojawia się w **jednym** przypadku:

   > Gdy **ostatnie** dziecko kontenera `space-y-*` jest `display:none`
   > (`hidden`/`md:hidden`/atrybut `hidden`), v4 zostawia `margin-bottom` na
   > przedostatnim dziecku → **dodatkowy pusty odstęp na dole kontenera**.
   > v3 tego nie robił.

   Skala: 661 kontenerów `space-y-*`, z czego **102 pliki** zawierają jednocześnie
   `space-y` i klasę `hidden` (górna granica — większość to nietrafienia, bo `hidden`
   jest zwykle na innym elemencie niż ostatnie dziecko).

   **To defekt wyłącznie kosmetyczny** — nadmiarowy odstęp, nigdy nachodzenie treści
   ani przesunięcie elementu. Warunkowe renderowanie React (`{cond && <X/>}`) jest
   **bezpieczne**, bo nie zostawia węzła w DOM, więc `:last-child` trafia poprawnie.

4. **Ekrany za logowaniem nie zostały porównane wizualnie** — harness `/preview/*` jest
   chroniony middlewarem (deny-by-default, wymaga realnego JWT). Pokrycie daje pośrednio
   macierz 56 kombinacji × 67 elementów tokenowych (§5.3), obejmująca wszystkie tokeny
   używane przez te ekrany.

## 8. Odpowiedź na uwagi automatycznego review

Review (`claude-code-action`) dał ✅ *Approve with notes* i zgłosił 3 uwagi. Sprawdzone:

**Uwaga 1 — zdublowany `@keyframes fadeIn`.** Potwierdzone: kodmod zostawił definicję
w `@theme inline` (dla zmiennej `--animate-fadeIn`) i w `@layer utilities` (dla ręcznie
pisanej klasy). W zbudowanym CSS obie definicje są **znakowo identyczne**, obie reguły
`.animate-fadeIn` dają `animation: fadeIn 200ms ease-out both`. Zero różnicy w działaniu.

**Zostawione świadomie.** Klasy `.animate-in` i `.fade-in` odwołują się do `fadeIn` przez
`animation-name`, a klatki z `@theme` są emitowane **tylko** gdy użyta jest odpowiadająca
im utility `animate-*`. Usunięcie jawnej definicji z `@layer utilities` sprawiłoby, że
zniknięcie ostatniego użycia `animate-fadeIn` po cichu urwałoby `.fade-in`. Redundancja
jest tu tańsza niż to ryzyko — i tak czy tak jest to sprzątanie do osobnego PR-a, nie do
bumpa zależności.

**Uwaga 2 — czy `--color-gray-200` jest w ogóle emitowane przy `@theme inline`?**
Sprawdzone w zbudowanym CSS: **jest** — `--color-gray-200: oklch(92.8% 0.006 264.531)`.
`@theme inline` z własną paletą nie wyłącza domyślnej palety v4, więc shim
`border-color: var(--color-gray-200, currentcolor)` działa jak zamierzono i nie degraduje
się cicho do `currentcolor`. **Uwaga bezpodstawna.**

> Poboczna obserwacja: dla samego `*` shim i tak jest bezprzedmiotowy, bo
> `* { @apply border-border }` (linia 503, ta sama warstwa, dalej w pliku) go nadpisuje.
> Shim pozostaje operatywny dla `::before`/`::after`/`::backdrop`, których `*` nie łapie.

**Uwaga 3 — `space-y-*`.** Zgodna z §7.3, gdzie rozbieżność jest już scharakteryzowana
pomiarowo (jedyny przypadek: ostatnie dziecko `display:none` → nadmiarowy odstęp na dole).

## 9. Zalecenie przed mergem

Przejść ręcznie (zalogowany) po: liście kandydatów, tablicy Kanban, generatorze CV,
modalach i trybie Kids. Konkretnie szukać **nadmiarowego odstępu na dole** list i paneli
(ryzyko #3) — reszta jest domknięta pomiarowo.
