# Wyłączenie konta zwalnia przypisania do rekrutacji (08.11.2026)

Audyt 2, B8: rekrutacja przypisana do nieaktywnego konta wyglądała na obsadzoną
(7 otwartych na 4 kontach). `deactivate_account` woła teraz
`release_assignments_safely` (`services/account_assignment_release.py`):

- żywe przypisania konta (`job_work_assignments`) schodzą z powodem
  `deactivated`, propozycje automatu z `proposal:deactivated`;
- prowadzący znika z OPUBLIKOWANYCH rekrutacji (`release_operator` + wpis
  `owner_released` z `reason: deactivated`). Zamknięte zachowują
  `jobs.recruiter_id`, bo wisi na nim historia i metryki;
- DL rekrutacji (przy braku aktywnego DL-a: HoR) dostaje dzwonek
  `recruiter_parked` „Rekrutacja straciła rekrutera”, bez maila. Sama propozycja
  automatu nie daje dzwonka;
- awaria nie zatrzymuje wyłączenia (savepoint + log), jak `hand_over_safely`;
- konto w toku odejścia z nieprzekazanymi rekrutacjami nic nie traci:
  `hr/handover.py` szuka ich po tych samych wierszach, więc zwolnienie
  zabrałoby pracę przejmującemu wskazanemu przez Kadry.

Konta wyłączone przed tą regułą domyka `python -m scripts.release_deactivated_accounts`
(domyślnie podgląd, `--apply` zapisuje). Rekrutacja P1 bez prowadzącego wpada we
wpis „Rekrutacja bez pracującego rekrutera”
(`powiadomienia/kandydat-utknal-jeden-wpis-na-rekrutacje.md`); poza P1 kończy się
na dzwonku przy zwolnieniu, bo bez prowadzącego to tam stan normalny.
