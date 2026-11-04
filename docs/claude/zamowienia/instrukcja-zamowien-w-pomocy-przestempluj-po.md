# Instrukcja zamówień w Pomocy — przestempluj po ZMIANIE LOGIKI ZAMÓWIEŃ

Pomoc → Procedury zawiera „Zamówienia — instrukcja dla Delivery Leada"
(`backend/app/data/procedures/zamowienia-instrukcja-delivery-lead.md`). Opisuje
ZACHOWANIE SYSTEMU — który przelicznik stosuje się u którego klienta, ile dni
przed końcem przyjdzie alert, co wypełni się samo z PDF-a. Taka treść psuje się
nie wtedy, gdy zmieni się proces w firmie, tylko wtedy, gdy ktoś zmieni parser
albo próg — a wtedy nikt nie ma powodu wchodzić do modułu Pomoc.

**Zmieniasz cokolwiek w logice zamówień → przejrzyj instrukcję i przestempluj:**

```bash
cd backend && python3 scripts/stamp_orders_procedure.py   # sprawdzenie bez zapisu: python3 scripts/check_stamps.py
```

`tests/test_orders_procedure_freshness.py` trzyma CI na czerwono, dopóki tego nie
zrobisz, i wypisuje po polsku, które pliki się zmieniły. Lista obserwowanych
plików (36 pozycji, backend + ekrany) siedzi w `app/data/procedures/__init__.py`.
Przegląd zakończony wnioskiem „ta zmiana nie dotyczy instrukcji" jest w pełni
poprawny i też kończy się przestemplowaniem — to nie jest obejście.

- **Treść jest w repo, nie tylko w bazie.** Jedno źródło (`.md`) czytają OBA
  kanały zasiewu: migracja `0254_orders_procedure_seed` i `_seed_repo_procedures`
  w `entrypoint.sh` (prod alembic bywa osierocony). Nie przepisuj treści do
  migracji — 40 KB w trzech miejscach rozjeżdża się przy pierwszej poprawce.
- **Zasiew jest UPSERT-em z warunkiem `procedures.updated_by IS NULL`.** Wdrożenie
  odświeża wiersz tak długo, jak nikt nie tknął go w aplikacji; edycja przez
  `PUT /api/procedures/{id}` stempluje autora i od tej chwili wiersz zostaje
  taki, jaki zapisał człowiek. Sama instrukcja mówi o tym czytelnikowi wprost.
- **Stemple są per plik** (`app/data/procedures/orders_stamps/<ścieżka z / → __>.json`,
  od #1776) — dwa PR-y zmieniające RÓŻNE pliki logiki zamówień nie zderzają się
  już na wspólnym stemplu; ten sam plik = konflikt, i słusznie (ktoś musi
  przejrzeć). Skrypt przepisuje tylko stemple, które się rozjechały (`--only`).
  **Data w treści zmienia się tylko przy edycji samej treści** (tekst ma własny
  stempel) — przegląd „ta zmiana nie dotyczy instrukcji” daty nie rusza, więc
  widoczna data może być starsza od ostatniego przeglądu, nigdy nowsza. Hook
  `review-stamps` w `.pre-commit-config.yaml` sprawdza stemple przed commitem.
- **Spis treści w module Pomoc** powstaje z DOM-u (`lib/procedure-headings.ts`),
  nie z parsowania Markdownu — parser po naszej stronie musiałby powtórzyć
  zachowanie `react-markdown` co do joty, a każdy rozjazd to link prowadzący
  w złe miejsce. Harness wizualny: `/preview/procedure-help`.
