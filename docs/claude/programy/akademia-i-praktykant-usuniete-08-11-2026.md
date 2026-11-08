# Akademia i Praktykant — usunięte z kodu 08.11.2026 (tabele zostały)

<!-- indeks: odtworzenie z commita 559db3992; rola trainee i tabele zostały -->

Decyzja Artura z 08.11.2026 (D1 z audytu 07.11.2026). Oba programy były ukryte
z interfejsu od 17.10.2026, a na kopii produkcji z 07.11 wszystkie tabele miały
0 wierszy. **Akademia ma wrócić, kiedy zdecyduje Artur**, dlatego ten plik mówi,
co zostało i skąd odtworzyć resztę.

## Jak odtworzyć

Ostatni commit `main` z pełnym kodem obu modułów: **`559db3992`**.

```bash
git diff --name-status 559db3992 HEAD -- backend/app frontend/src | grep -iE "academy|trainee"
git checkout 559db3992 -- backend/app/api/academy.py backend/app/services/academy.py
```

Opis zachowania (reguły naboru, sortowanie Luną, dokumenty, listy telefonów,
bramki) jest w historii tych plików reguł: `git log --follow --
docs/claude/programy/akademia-i-praktykant-usuniete-08-11-2026.md`, a kontrakt
praktykanta w `git show 559db3992:docs/trainee-call-lists-contract.md`.

Przy powrocie Akademii:

- zwolnij adresy w `api/retired_modules.py` (dziś 410) i przekierowania
  w `frontend/next.config.ts`,
- przywróć pętlę `academy_intake` w `main.py`, wpis w `core/staging.py`
  (`STAGING_BLOCKED_TASKS`) i w `loop_heartbeat.EXEMPT`,
- nie buduj filtra po imieniu, narodowości ani wieku (odmowa z 24.09.2026), a
  wykluczenie zawsze klika człowiek (umowa uczestnictwa, §5a ust. 8).

## Co zostało w kodzie

- **Tabele i modele:** `models/academy.py`, `models/academy_logistics.py`,
  `models/trainee.py`, migracje 0369, 0374, 0465 i lustro w `entrypoint.sh`.
  Czytają je scalanie kandydatów i twarde usuwanie.
- **Rola `trainee`** w słownikach ról i bramkach (0 kont). Bez ekranu; konto
  z tą rolą dostawałoby 403.
- **Kolumny `candidates`** z rozmowy praktykanta (`b2b_willingness`,
  `accepts_below_min_rate`, `work_time_preference`…) i bramki
  `dealbreaker_filters`, a także `PATCH /api/candidates/{id}/call-facts`.
- **`AIFeatureKey.academy_screening`** z wyborem modelu: wiersz w `ai_features`
  istnieje na produkcji. Sam prompt usunięty.
- **Sprzęt:** typ posiadacza `academy` i kolumna `academy_application_id` do
  odczytu historii (0 wydań). Zakładka „Akademia” i tryb „Uczestnik Akademii”
  w kreatorze zdjęte.

## Co zniknęło

Trasy `/api/academy/*`, `/api/trainee/*`, `/api/integrations/v1/academy/*`
(wszystkie 410), scope `academy:read`, pętle `academy_intake` i
`trainee_call_lists`, strony `/academy`, `/trainee`, `/trainees`,
`/settings/trainee-rules` (przekierowanie na start albo do Ustawień), harnessy
`/preview/academy` i `/preview/trainee*`, szablony `app/templates/academy/`.
