# Generator Umów B2B — poprawka nazwy Nordea + autouzupełnianie opisu z obszaru

Data: 2026-08-03 · PR [#1030](https://github.com/artur-t-96/Nexus/pull/1030) ·
branch `claude/contract-generator-nordea-services-85326e`

Dwie usterki z QA generatora umów B2B (jeden ekran „Klient i projekt").

## 1. „Nordea ABP" → „Nordea Bank Abp" w liście wyboru Klienta

**Objaw:** w polu „Pełna nazwa Klienta" Nordea widniała jako „Nordea ABP".

**Przyczyna:** dropdown Klienta renderuje `clients.display_name`
(`GET /api/clients-lookup?featured=true` → `coalesce(display_name, name)`).
Rekord Nordea (prod `id=11`) miał błędne ręczne nadpisanie
`display_name = "Nordea ABP"`; poprawna, pełna nazwa była już w
`legal_name = "Nordea Bank Abp"`.

**Fix:** migracja `0210_fix_nordea_display_name` — idempotentny `UPDATE`
scope'owany po `name = 'Nordea'` + dokładnej złej wartości. Scope po `name`
(nie `id`) zostawia fix przenośnym między środowiskami. Downgrade odwraca.

## 2. Opis §1 nie uzupełniał się po wyborze obszaru usług

**Objaw:** po wybraniu obszaru w „Obszar usług (§1 umowy)" pole „Opis projektu
i zakres usług" zostawało puste.

**Przyczyna:** efekt smart-prefillu bramkował się na *samej wybranej ofercie*
(`selectedRecruitment`), a nie na tym, czy opis realnie z oferty pochodzi:

```ts
if (!selectedRole || selectedRecruitment || descTouched.current) return;
```

W dominującym flow („Wybierz kandydata i konkretną rekrutację" — wymagane w
sekcji „Źródło danych") użytkownik ma wskazaną ofertę. Gdy oferta nie niosła
opisu, warunek `selectedRecruitment` blokował autouzupełnienie z obszaru i pole
zostawało puste. Flow czysto ręczny (bez oferty) działał — potwierdzone na
prodzie przed poprawką.

**Fix:** o nadpisaniu decyduje teraz wyłącznie `descTouched`. Opis z oferty i
ręczne zmiany nadal mają priorytet — jedno i drugie ustawia `descTouched`, a
efekt oferty jest zadeklarowany wyżej, więc w tym samym commit wykona się
pierwszy i zdąży ustawić flagę. Sam wybór obszaru zawsze wypełnia puste pole
gotowym opisem (bez znamion UoP). Logika wyniesiona do czystej, testowalnej
funkcji `areaPrefillDescription`.

## Pliki

- `backend/alembic/versions/0210_fix_nordea_display_name.py` (nowy)
- `frontend/src/components/v2/pages/B2BContractGeneratorV2.tsx` (efekt +
  helper `areaPrefillDescription`)
- `frontend/src/components/v2/pages/__tests__/B2BContractGeneratorPrefill.test.tsx`
  (nowy, 6 asercji)

## Weryfikacja

- `npm run type-check` ✅ · `next lint` 0 warnings na zmienionych plikach ✅
- `vitest run` — 208/208 (w tym 6 nowych) ✅ · `ruff` na migracji ✅
- Łańcuch alembic: `0210` jedyną głową (`down_revision = 0209`); prod na `0209`
  (alembic żywy) → wchodzi na deployu.
- Prod „przed" (Chrome): dropdown pokazuje „Nordea ABP"; wybór obszaru w flow
  ręcznym wypełnia opis (potwierdza, że przyczyna to bramka na ofercie).
- Prod „po" (Chrome, po deployu): _do uzupełnienia po merge._

## Znane ograniczenia / uwagi

- Priorytet „opis z oferty" opiera się na kolejności deklaracji efektów
  (oferta wyżej niż obszar). Udokumentowane komentarzem przy efekcie; zmiana
  kolejności złamałaby regułę bez błędu typów — świadomy, znany inwariant.
