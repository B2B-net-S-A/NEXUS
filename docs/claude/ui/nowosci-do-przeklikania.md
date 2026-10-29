# Nowości do przeklikania zamiast artefaktu „co nowego”
<!-- indeks: rejestr `app/data/novelties/novelties.json`, trzy poziomy (dot/tour/process), zaliczenie z pracy, panel admin + HoR, `novelty_progress` (0617) -->

Decyzja Artura z 28.10.2026 (makiety: https://claude.ai/artifact/Qmy51h287jZy4r9oCaA1i4).
Ludzie nie czytali artefaktów „co nowego” ani dymków: w 30 dni do 27.10
Jarvis pokazał 478 dymków 46 osobom, a przewodnik ekranu otworzyła jedna.
Nowość ma więc wejść w drogę pracy i zaliczać się z pracy.

- **Każda nowość, którą ludzie mają zauważyć, to wpis w
  `backend/app/data/novelties/novelties.json`** w PR-ze, który ją wdraża.
  Ten wpis zastępuje artefakt „co nowego” i ręczne „daj znać”. Treść jest dla
  użytkownika: bez tras, nazw tabel i numerów zgłoszeń w `why`.
- **Poziom (`tier`) decyduje, jak mocno nowość wchodzi w drogę:**
  `dot` (drobiazg) to sama kropka na elemencie, zaliczona pierwszym kliknięciem;
  `tour` (nowa funkcja) to kropka i karta „Przeklikaj” z krokami;
  `process` (zmiana procesu, czyli coś, co trzeba teraz robić inaczej) to okno
  przy pierwszym wejściu na `path_prefix`, które można odłożyć raz, do 8:00
  następnego dnia. Nie podnoś poziomu „na wszelki wypadek”: okno przy każdej
  nowości nauczy ludzi klikać „dalej” na ślepo.
- **Zaliczenie = przeklikanie (`tour`) albo użycie w pracy (`used`, klik
  w `used_anchor` poza przeklikaniem)**. Przycisku „Przeczytałem” nie ma
  i nie dokładamy go. Demo wideo odrzucone 28.10.
- **Kroki chodzą po kotwicach `data-tour="<id>"`** na prawdziwych elementach.
  Krok przechodzi po kliknięciu kotwicy, nie po „Dalej”. Krok, którego nie
  wolno wykonać naprawdę (zapis zakończenia kontraktu), ma `ack: true`
  i przechodzi przyciskiem „Rozumiem”. Kotwica bez elementu we froncie
  oznacza czerwony test frontu.
- **Odbiorcy:** `audience.roles` albo `audience.permissions` (wystarczy jedno,
  pusto = wszyscy). Przycisk widoczny dla uprawnienia opisujesz uprawnieniem.
  Nowość żyje 45 dni (`active_days`), a panel pokazuje ją do 90 dni.
- **Panel „Nowości — kto już umie” (`GET /api/novelties/adoption`)** widzą
  tylko admin i Head of Recruitment (`HeadOfRecruitmentPlus`), bo pokazuje
  imiennie, kto jeszcze nie umie. „Przypomnij” przywraca kartę przy kropce
  i nie wysyła maila.
- **Karta przy kropce wchodzi do wspólnego budżetu dymków (3 dziennie,
  `lib/jarvis/bubble-budget.ts`)**. Nie dokładaj osobnego źródła dymków.
  W trybie podglądu jako inna osoba zdarzenia się nie zapisują.
- **Schemat:** `novelty_progress` (0617), DDL w `app/services/novelty_schema.py`,
  lustro w `entrypoint.sh`, sonda w `/api/health/deep`.
