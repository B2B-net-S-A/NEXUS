# NEXUS bez limitów AI (decyzja Artura, 17.09.2026)

Nie ma już głównego wyłącznika AI, przełączników per funkcja ani miesięcznych
sufitów. Jedyną ochroną budżetu jest **alarm wydatków** (`app/tasks/ai_spend_alerts.py`),
który informuje administratorów i niczego nie zatrzymuje.

- **`ai_quota.check_and_increment` nigdy nie rzuca.** Zostaje, bo zapisuje
  `AIOperation` — na nim stoją liczniki w Ustawieniach → AI i alarm. Kontekst
  `ai_feature()` MUSI zostać przy każdym wywołaniu modelu (telemetria kosztów,
  `_assert_declared`). Pilnują tego `test_ai_quota_monthly_limit.py`
  (stare kolumny nie blokują, zużycie rośnie) i `test_ai_quota_provider_gate.py`.
- **Kolumny `ai_features.enabled` / `monthly_limit` i wiersz `ai_master_toggle` są
  martwe.** Nic ich nie czyta jako bramki, a trasy `PATCH /api/settings/ai/master`
  i `/features/{feature}` zniknęły. Nie przywracaj bramki czytającej te kolumny:
  panel nie pozwala ich zmienić, więc stara wartość z bazy blokowałaby po cichu.
- **`AIQuotaExceeded` zostaje jako klasa** — importuje ją kilkanaście modułów,
  a ich gałęzie `except` są martwym, nieszkodliwym kodem. Do sprzątnięcia przy okazji.
- **Czat publicznego interaktywnego CV** zależy wyłącznie od polityki klienta
  (`cv_interactive_enabled`) i dziennego limitu per link
  (`CV_INTERACTIVE_CHAT_DAILY_LIMIT`, obrona przed nadużyciem publicznego linku).
- **`EXPERIENCE_DATES_ON_DEMAND_ENABLED` domyślnie `True`** (wyłącznik awaryjny).
- Ustawienia → AI to raport: model, tokeny, koszt per funkcja, suma miesiąca, alarm.
