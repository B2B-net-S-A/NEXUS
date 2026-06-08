# UI recolor — profesjonalny system kolorów (2026-06-08)

Commit `2daaf34` · zdeployowane na `nexus.dynaminds.pl` · zweryfikowane przez Chrome MCP (light + dark).

## Cel

UI wyglądał nieprofesjonalnie. Przyczyną był **dobór wartości**, nie architektura
(shadcn + zmienne CSS HSL były OK). Trzy realne problemy:

1. `--accent` = `--primary` (ta sama mocna barwa) → krzykliwe hovery w menu/dropdownach.
2. Sidebar = duży nasycony blok koloru (fioletowy) → niezgodne z nowoczesnym SaaS.
3. Podbarwione tła per-paleta → całe chrome tinowane.

Kierunek (wybrany przez użytkownika): **neutralny chłodny slate + indygo + neutralny
sidebar** (styl Linear/Vercel/Notion), `accent` rozdzielony od `primary`.

## Co się zmieniło

| Plik | Zmiana |
|------|--------|
| `frontend/src/app/globals.css` | Przepisany system tokenów: neutralna baza slate (light+dark), akcent indygo, **`--accent` neutralny ≠ `--primary`**, neutralny sidebar. Bloki per-paleta zredukowane do 3 zmiennych. |
| `frontend/src/components/v2/shell/SidebarV2.tsx` | ~15 hardkodów `white/x`/`text-white`/`border-white/10` → tokeny. Aktywna pozycja: `bg-primary/10` + lewy pasek akcentu (rozwinięty) / `text-primary` (collapsed). |
| `frontend/src/store/theme.ts` | Dodane **indygo** (domyślne), violet zachowany; migracja persistu `v4→v5`. |
| `frontend/src/app/layout.tsx` | Bootstrap anti-flash: default + allow-list + fallback → indygo. |
| `frontend/src/lib/colors.ts` (nowy) | Wspólne `AVATAR_COLORS`/`getAvatarColor` (koniec zduplikowanego `bg-violet-600`). |
| `compare/page.tsx`, `AddCandidatesQuickModal.tsx`, `jobs/[id]/page.tsx` | Użycie wspólnego utila; stray violet (button + ring) → `primary`. |

## Architektura systemu motywów (po zmianie)

- **Chrome + sidebar są NEUTRALNE i wspólne** — zdefiniowane raz w `:root` / `.dark`.
- Bloki `[data-theme="x"]` / `.dark[data-theme="x"]` nadpisują **tylko** `--primary`,
  `--primary-foreground`, `--ring`. Przełączenie palety zmienia **wyłącznie akcent**;
  tła, karty, sidebar zostają neutralne.
- **Indygo = domyślne** (w `:root`/`.dark`, bez bloku `[data-theme]`). 7 palet w pickerze:
  Indygo, Fiolet, Niebieski, Zielony, Pomarańcz, Róż, Grafit.
- Dodanie nowej palety = 1 blok 3-liniowy w `globals.css` + wpis w `THEME_PALETTES`
  (theme.ts) + dopisanie do allow-listy w bootstrapie (`layout.tsx`).
- Wszystkie pary `primary`/`primary-foreground` skontrastowane pod **WCAG AA ≥ 4.5:1**
  (zielony/pomarańcz przyciemnione w light, by przeszły na białym).

## Weryfikacja

- Lokalnie: `tsc --noEmit` ✓, `next lint` ✓ (tylko pre-existing warningi), `next build` ✓.
- Prod (Chrome MCP, nexus.dynaminds.pl): computed `--accent` = `220 16% 93%` ≠ `--primary`
  (split potwierdzony), `--sidebar` = `220 20% 97%` (neutralny), migracja persistu `version:5`
  zachowała wybór użytkownika. Light + dark zrzuty: neutralne chrome, neutralny sidebar
  z akcentem na aktywnej pozycji, indygo przyciski/badge, logo Dynaminds widoczne
  (`currentColor`). Palette-independence potwierdzona (green vs indigo: to samo neutralne chrome).

## Świadomie poza zakresem

- **Kolory statusowe** (red/amber/emerald) — zostają (poprawna praktyka SaaS).
- **Wykresy recharts** w `dynareporter/*` + `DlTrendChart` — stałe hex serii kategorialnych,
  nie kolidują z neutralnym chrome, a routy są ukryte z nawigacji. Do ewentualnego
  follow-upu (centralizacja do `CHART_SERIES`).
- **Logo zewnętrzne** (Microsoft/LinkedIn) — bez zmian.

## Do ewentualnej oceny wzrokowej (drobne)

- Aktywny tekst nav w dark = `text-foreground` (AA-safe); akcent niesie fill + pasek.
- Pomarańcz light przyciemniony (40%L) by przejść AA; można rozjaśnić z ciemnym tekstem.
- Grafit: akcentowy fill aktywnej pozycji bardzo subtelny (monochrom) — ew. `bg-primary/15`.
