# Migawka `credited` raz na minutę — konsumenci nie liczą `VERIFIER_ANCHORED_CTE` sami
<!-- indeks: CREDITED_FROM_SNAPSHOT_CTE + credited_bind, wąskie process_windows, wyjątki ze świeżym CTE, kafel „Wyniki zespołu” jednym zapytaniem -->

27.10.2026 NEXUS lagował: jedno `VERIFIER_ANCHORED_CTE` to na produkcji 2,2 s
bez JIT, w 5 minutach było 16 wywołań i 53% czasu bazy, a sortowanie `rp.*`
w `process_windows` zrzuciło na dysk ok. 100 GB. Każdy konsument filtrował
osobę, etap i okno dopiero na wyniku CTE, a sam wynik (`credited`) ma
ok. 14 tys. wierszy (kopia produkcji z 22.10.2026).

- **`services/credited_snapshot.py`** liczy `credited` całej firmy raz na
  minutę (`cache_single_flight`, proces uvicorna ma jeden cache).
  Konsument dokleja `CREDITED_FROM_SNAPSHOT_CTE` zamiast
  `VERIFIER_ANCHORED_CTE` i dokłada parametry `await credited_bind(db, …)`.
  Reszta jego SQL-a zostaje bez zmian, więc liczby są te same co do jednej.
  Pilnuje tego `tests/test_credited_snapshot.py`: każde zapytanie konsumenta
  wykonuje drugi raz z pełnym CTE i porównuje wiersze.
- **Zawężenie w `credited_bind`** (`credit_user`, `stage`, `since`/`until`
  półotwarte) podawaj tylko wtedy, gdy SQL konsumenta stosuje ten filtr do
  KAŻDEGO odczytu `credited`. Panel osoby zawęża do osoby (kohorta precyzji
  i tak łączy po osobie), lista „Kto się liczy” do etapu i okresu.
- **Nowy konsument zasługi = migawka**, nie własne CTE. Świeże
  `VERIFIER_ANCHORED_CTE` zostaje tylko tam, gdzie minuta opóźnienia zmienia
  wynik: mail „Nowy placement” (`board_placement_alerts._credit_user`
  i `competition_rules.placement_margin_per_hour_by_user` — pytają o placement
  sprzed chwili), zawężona kopia Priority Work, rekonsyliacja i adopcja
  procesu (czytają `credited_nexus`). `freeze_competition` przed policzeniem
  podium woła `invalidate_credited_snapshot()`.
- **`process_windows` wybiera tylko czytane kolumny** procesu (także
  `eligibility_assignment_id` dla Priority Work). Nowa kolumna czytana
  z `classified_process` = dopisz ją tam, inaczej zapytanie padnie.
- **Świeżość:** ruch na Tablicy widać w liczniku po najwyżej ok. 2 min
  (migawka 60 s + cache konsumenta 60 s); wcześniej po 60 s.
- **Kafel „Wyniki zespołu”** pyta raz `GET /api/dashboard/v2/recruitment-activity/team-totals`
  (kilka `metric` naraz) zamiast czterech list. Liczba etapu to `period_total`
  listy zespołu — to samo zapytanie podsumowania, ta sama bramka (403 bez
  wglądu w zespół).
