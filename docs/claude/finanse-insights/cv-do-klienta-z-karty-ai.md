# Kafelek „CV do klienta z karty AI” w Insights → Zespół (22.11.2026)
<!-- indeks: decyzja Artura R6 z 22.11.2026, udział pierwszych cv_sent pary z procesem entry_source='system', tydzień kalendarzowy firmy pon–niedz, bieżący i 4 poprzednie, cel 100% stałą, `GET /api/insights/recruitment/cv-from-ai-card`, `TeamAiCardCvTile`, bez JOIN jobs -->

Cel Artura: osoby, które proponuje AI w porcji dnia, mają być osobami, które
wysyłamy klientom. Do 22.11.2026 udział liczyło ręczne zapytanie SQL; decyzja
Artura z 22.11.2026 (rekomendacja R6, raport:
https://claude.ai/artifact/Ec7UJD6UbQqwe4HgSiebZW) zrobiła z niego kafelek dla
Head of Recruitment. Kod: `backend/app/services/insights_ai_card_cv_share.py`,
front `components/insights/views/team/TeamAiCardCvTile.tsx`.

- **Mianownik:** pierwsze wejście pary (rekrutacja, kandydat) w `cv_sent`
  (`min(moved_at)` z `candidate_stages`) w tygodniu kalendarzowym firmy
  (Europe/Warsaw, pon–niedz, „dziś” z `business_today()`). Druga wysyłka tej
  samej pary nie jest nowym CV.
- **Licznik:** z tych wysyłek te, w których najnowszy proces pary otwarty nie
  później niż wysyłka (`opened_at <= t`, `ORDER BY opened_at DESC LIMIT 1`) ma
  `entry_source = 'system'` (karta od porcji albo silnika). Proces otwarty po
  wysyłce, np. ponowna próba z porcji, nie przypisuje jej karcie wstecz.
  Para bez procesu otwartego przed wysyłką liczy się tylko w mianowniku.
- **Cała firma, bez `JOIN jobs` i bez filtra klienta**, jak ręczne zapytanie;
  bez twardo wpisanych id rekrutacji.
- **Okno stałe:** bieżący tydzień (z dopiskiem „trwa”) i 4 poprzednie,
  niezależnie od okresu zakładki. Liczby: wysłane CV, z karty AI, udział.
- **Cel 100%** to stała `TARGET_PCT` w kodzie, nie ustawienie. Nie obniżaj
  jej, żeby kafelek wyglądał lepiej: kafelek mierzy odległość od celu.
- **Tydzień bez wysyłek to „—”, nie 0%** (`share_pct = None`). Awaria zapytania
  ma własny komunikat (`apiErrorMessage`), pusty stan tylko po udanym zapytaniu.
- **Dostęp:** bramka sekcji Insights z routera (`INSIGHTS_SECTION_DEPENDENCIES`),
  jak pas „Od otwarcia rekrutacji do pierwszego CV”. Same liczby firmy, bez
  nazwisk i kwot, więc bez `view_team_kpi`.

Punkt wyjścia z produkcji (ręczne zapytanie): 09–13.11 25%, 16–19.11 23%,
20.11 31%.
