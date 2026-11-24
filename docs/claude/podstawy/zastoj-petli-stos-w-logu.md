# Zastój pętli zdarzeń: stos w logu (`loop_stall`)

Od 24.11.2026 (decyzja Artura) każdy proces backendu (web i worker) uruchamia razem
z pętlą `runtime_metrics` strażnika `app/tasks/loop_stall_guard.py`. Gdy pętla zdarzeń
stoi dłużej niż `LOOP_STALL_DUMP_SECONDS` (domyślnie 5 s, `0` wyłącza), proces loguje
jedną linię JSON `event_kind: "loop_stall"` z polem `frames`: stos wątku pętli
z chwili 5 s po początku zastoju, najnowsza ramka pierwsza (`plik:linia funkcja`).

Powód: 24.11.2026 proces web stawał po 52 s (CPU 86–100%, bez pełnego GC), wszystkie
żądania czekały, przeglądarki zrywały je po 30 s. Na stagingu się nie odtwarzało,
a `runtime_metrics` mówi tylko, że pętla stała, nie gdzie.

- Odczyt: `prod_readonly.py logs --since 2h` przepuszcza `loop_stall` obok
  `runtime_metrics` i `http_outcome`.
- Szukaj pierwszej ramki z `app/` — to linia, która trzyma pętlę. Ramki z bibliotek
  nad nią (`site-packages`) mówią, czy to np. serializacja albo regex.
- Zrzut robi wątek C `faulthandler`, więc działa także wtedy, gdy kod trzyma GIL.
  Plik roboczy: `/tmp/nexus-loop-stall-<pid>.txt`, czyszczony po każdym zgłoszeniu.
- W logu są tylko ścieżki, numery linii i nazwy funkcji, bez wartości zmiennych.
  Nie dokładaj tu treści ramek ani zmiennych lokalnych: logi czyta rutyna.
