# Jarvis: zapis łatwy do cofnięcia od razu, z „Cofnij” (27.10.2026)
<!-- indeks: JarvisTool.undo, actions.execute_now / undo_action, POST /api/jarvis/actions/{id}/undo, okno 15 min, zamknięta lista _UNDO_ROUTES, tylko na wyraźną prośbę, pominięci -->

Decyzja Artura z 27.10.2026 (zmienia zasadę z 21.09 „zapis tylko po
kliknięciu”): na produkcji 4 z 4 przygotowanych kart „Zrób to” wygasły bez
kliknięcia. Zapisy łatwe do cofnięcia wykonują się od razu w turze, a karta
pokazuje „Zrobione za Ciebie” i „Cofnij” przez 15 minut.

- **Które**: `create_note`, `add_candidates_to_job`, `snooze_my_person`,
  `pin_my_person` — te z polem `undo` w `tools.py`. Zamkniętą listę i trasy
  odwrotne pilnuje `test_jarvis_tool_registry_contract.py` (`_UNDO_ROUTES`).
  Nowe narzędzie z `undo` = decyzja Artura. Reszta zapisów (ruch na tablicy,
  debrief, kalendarz, werdykt, pula, pamięć…) dalej czeka na „Zrób to”.
- **Opis narzędzia** zaczyna się od „WYKONUJE OD RAZU” (z `undo`) albo
  „PROPONUJE” (bez) — model wie, czy zapis już się stał.
- **Wykonanie w turze** (`actions.execute_now`) nie dopisuje notatki
  „[Wynik akcji]” do historii: wiadomość w środku tury rozdzieliłaby
  `tool_use` od wyniku. Model dostaje wynik w `tool_result` („WYKONANO od
  razu…”), a front zdarzenie `action_proposed` z akcją `executed`, komunikatem
  i kluczami do odświeżenia ekranu.
- **Cofnij**: `POST /api/jarvis/actions/{id}/undo` — tylko własna akcja,
  w oknie `UNDO_WINDOW_MINUTES` od wykonania, jeden raz (`undo_state`:
  `available → running → done|failed` warunkowym UPDATE w `result`, bez
  nowego statusu i bez migracji CHECK-a). Wywołania odwrotne idą tokenem
  klikającego; 404 trasy odwrotnej liczy się jako cofnięte (już tego nie ma).
  `undo_calls` nie wychodzą do frontu (`_public_result`).
- **Dodanie do rekrutacji** cofa `DELETE /api/candidates/{id}/recruitments/{job}?quick_undo=true`
  dla każdej dodanej osoby — ten sam tryb, co „Cofnij” w oknie „Kandydaci do
  dodania” (15 min, osoba wraca na listę propozycji). Notatka dołączona do
  dodania zostaje w profilu.
- **Model woła te narzędzia tylko na wyraźną prośbę.** Skoro zapis dzieje się od
  razu, `prompt.py` nie może go kazać „proponować”: sekcja o przepinaniu „Moich
  ludzi” wymienia pasujących, a dodaje dopiero, gdy użytkownik wskaże kogo.
- **Notatka ze wzmianką czeka na „Zrób to”** (`agent._runs_at_once`). Wzmianka to
  dzwonek i mail do innej osoby (`notes.py`, `mention_dispatch.py`), a usunięcie
  notatki wycofuje tylko dzwonek. Przegląd przed PR-em 04.11.2026: bez tego Jarvis
  wysyłałby maile bez kliknięcia, a „Wysyłka maila” jest na liście operacji, których
  nie wykonuje. Karta po kliknięciu nie ma „Cofnij”, jak każdy zatwierdzony zapis.
  Notatka podana przy dodaniu do rekrutacji nie czyta wzmianek, więc tego nie dotyczy.
- **Pominięci nie giną.** `POST /api/jobs/{id}/proposals/bulk` odpowiada 200 także
  przy pominięciu osób, więc model dostaje odpowiedź systemu w `tool_result`.
  Gdy trasa nikogo nie dodała, akcja kończy się `failed` z powodami pominięcia
  (`_nothing_added`), bez „Zrobione za Ciebie” i bez „Cofnij”.
- **Czego „Cofnij” nie przywraca:** zdejmuje zapis, nie odtwarza stanu sprzed
  niego. Ponowne przypięcie już przypiętej osoby i cofnięcie zostawia ją
  odpiętą, a przypięcie uśpionej zdejmuje też uśpienie. Sprzątamy to na liście
  „Moi ludzie”.
- **Stan zawsze się domyka.** Wyjątek w wywołaniu odwrotnym daje `failed`, a
  `running` po zamknięciu okna (restart w trakcie) pokazuje się jako `failed`.
- **Pusty panel i Pomoc mówią to samo:** grupa `now` w `capabilities.py` to dokładnie
  narzędzia z `undo` (test `test_now_lists_exactly_the_tools_with_undo`), a Pomoc
  opisuje je w `app/data/procedures/jarvis-asystent.md`.
