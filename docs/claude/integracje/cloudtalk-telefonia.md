# CloudTalk (telefonia) — usunięty z kodu 08.11.2026

<!-- indeks: integracji nie ma; model Call zostaje, KPI rozmów milczy -->

Decyzja 28.07.2026: nie używamy CloudTalka (koszt). Na produkcji w tabeli
`calls` było 10 wierszy (ostatni 14.04.2026) i ani jednego z CloudTalka.
Usunięcie z kodu: D1 z audytu 07.11.2026.

- **Nie ma już:** `/api/cloudtalk/*`, `POST /api/calls/webhook`,
  `GET /api/calls/cloudtalk-status` (wszystkie odpowiadają 410,
  `api/retired_modules.py`), pętli `cloudtalk_sync`, zmiennych `CLOUDTALK_*`,
  przycisku „Zadzwoń” w szybkim podglądzie i karty w Ustawieniach.
- **Zostaje:** model `Call` i kolumny `calls.cloudtalk_*`,
  `users.cloudtalk_agent_id`, rejestr rozmów dodawanych ręcznie, wartość
  `SuggestionSource.cloudtalk_call` (historyczne wiersze).
- **KPI rozmów** nie istnieje, dopóki `kpi_catalog.TELEPHONY_AVAILABLE` jest
  `False` (nie ma „0/15” ani nudge'a).
- **Następna telefonia** zaczyna od zera: stary kod jest w historii gita
  (ostatni commit z integracją to rodzic PR-a usuwającego).
