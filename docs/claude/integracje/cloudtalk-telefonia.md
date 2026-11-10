# CloudTalk (telefonia) — usunięty z kodu 08.11.2026, kolumny zdjęte 11.11.2026

<!-- indeks: integracji nie ma; model Call zostaje, KPI rozmów milczy, zostają tylko zaślepki 410 -->

Decyzja 28.07.2026: nie używamy CloudTalka (koszt). Na produkcji w tabeli
`calls` było 10 wierszy (ostatni 14.04.2026) i ani jednego z CloudTalka.
Usunięcie z kodu: D1 z audytu 07.11.2026. Artur 10.11.2026: „CloudTalk nie
używamy i można to w ogóle wywalić”.

- **Nie ma już:** pętli `cloudtalk_sync`, zmiennych `CLOUDTALK_*` (także
  w `.env.example`, compose i rejestrze flag), przycisku „Zadzwoń” w szybkim
  podglądzie, karty w Ustawieniach, wartości `cloudtalk_call` w enumie
  `SuggestionSource` i na froncie, pola „Agent CloudTalk” w oknie rozmowy.
- **Baza (migracja 0681, lustro w `entrypoint.sh`, decyzja Artura 11.11.2026):**
  zdjęte `calls.cloudtalk_call_id`, `calls.cloudtalk_agent_id`,
  `users.cloudtalk_agent_id` z indeksami. Odczyt produkcji 10.11.2026: 0 z 10
  rozmów miało id rozmowy albo agenta, id agenta miało 1 konto. Lustro
  jednorazowego cutoveru 0210 w entrypoincie już tej kolumny nie czyta
  (`test_telephony_columns_dropped.py`).
- **Zostaje celowo:**
  - zaślepki 410 dla `/api/cloudtalk/*`, `POST /api/calls/webhook`,
    `GET /api/calls/cloudtalk-status` (`api/retired_modules.py`, decyzja
    Artura 11.11.2026): nic nie kosztują, a stary webhook dostaje jasny
    komunikat zamiast 404; maskowanie tokenu `calls/webhook` w logach zostaje
    z tego samego powodu;
  - etykieta `cloudtalk_call` w typie Postgresa `champion_suggestion_source`
    (0 wierszy; Postgres nie usuwa etykiet enuma, przebudowa typu nie jest
    warta ryzyka, decyzja Artura 11.11.2026);
  - model `Call` i rejestr rozmów dodawanych ręcznie (`POST /api/calls`),
    z których korzystają follow-upy, aktywność kandydata i KPI. Follow-up
    przypina rozmowę wychodzącą tego konta po `call_id`, bez warunku na id
    z CloudTalka;
  - wpisy historyczne w inwentarzu funkcji profilu kandydata, stare migracje
    i raporty w `docs/`.
- **KPI rozmów** nie istnieje, dopóki `kpi_catalog.TELEPHONY_AVAILABLE` jest
  `False` (nie ma „0/15” ani nudge'a); pole katalogu to `requires_telephony`.
- **Rozmowy Sprzedaży** to osobny świat: `sales_activities` (kind `call`)
  i `sales_call_records`, bez telefonii.
- **Następna telefonia** zaczyna od zera: stary kod jest w historii gita
  (ostatni commit z integracją to rodzic PR-a usuwającego).
