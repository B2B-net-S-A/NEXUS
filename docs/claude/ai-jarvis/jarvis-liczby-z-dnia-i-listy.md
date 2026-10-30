# Jarvis: liczby z jednego dnia i imienne listy (27.10.2026)
<!-- indeks: activity_people → /api/dashboard/v2/recruitment-activity/details, okno day/week/month/range, scope team|auto -->

Na produkcji „ile osób w piątek zweryfikowano?” i „wymień osoby z
placementem” kończyły się bez odpowiedzi: `evaluate_metric` ma najkrótszy
okres 7 dni, grupuje tygodniami i zwraca same liczby.

- **`activity_people`** czyta tę samą listę, co klik w liczbę lejka
  w Insights (#2653): `GET /api/dashboard/v2/recruitment-activity/details`.
  Weryfikacje, rekomendacje, rozmowy u klienta, akceptacje, placementy —
  w dniu, tygodniu, miesiącu albo od–do, z osobą, która ma zasługę.
- **Nie rozszerzaj silnika metryk pulpitu** (`custom_metrics`) o dzień dla
  Jarvisa: te same okresy ma kreator kafelków na froncie. Liczby dzienne
  i listy idą przez tę trasę.
- `scope=team` dostaje rola z wglądem w zespół; innym trasa odpowiada 403 —
  Jarvis podaje wtedy liczby tej osoby i mówi, że zespołu nie widzi.
- Prompt: konkretny dzień/tydzień/od–do i „kto…” → `activity_people`;
  dłuższe trendy, nowi kandydaci, kontrakty i przychód → `evaluate_metric`.
