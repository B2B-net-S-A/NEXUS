# Imię cyrylicą w dopasowaniu maili i w bramce CV (20.10.2026)

Kandydat z imieniem albo nazwiskiem zapisanym cyrylicą (20.10.2026 w bazie 67 osób)
nie ma po złożeniu do ASCII ani jednej litery.

- **Dopasowanie maila po temacie** (`smart_name`, `app/services/m365/matcher.py`):
  `name_folds_to_nothing` = taki kandydat nigdy nie pasuje. Do 26.09.2026 pusty
  wzorzec `\b\b.*\b\b` pasował do każdego tematu: trzech kandydatów zebrało
  4 701 cudzych maili, a `smart_thread` doklejał im kolejne odpowiedzi.
  Nie usuwaj tego warunku przy „uproszczeniu” `_contains_name`, bo filtr SQL
  przed nim (słowa tematu `[a-z]+`) to dziś jedyna inna osłona.
- **Bramka tożsamości CV z maila** (`attachment_handler.try_parse_cv`):
  `identity_unreadable` = bramka zawsze daje `inconclusive`, więc nie odróżnia
  CV tej osoby od cudzego. CV z maila trafia do profilu jako zwykły plik
  (`parse_error = identity_unreadable_not_primary`): nie zostaje głównym CV
  i nie nadpisuje tekstu CV ani pól. Główne CV wskazuje człowiek (decyzja
  Artura z 20.10.2026).
  **Wyjątek (22.10.2026, decyzja Artura, audyt F68):** gdy kandydat powstał
  z tego CV (`try_create_candidate_from_cv`) albo jest dopasowany po e-mailu
  z tego CV (także po kolizji zapisu tego adresu), tożsamość jest pewna:
  `try_parse_cv(..., identity_proven=True)` pomija bramkę `identity_unreadable`,
  CV zostaje głównym i jest czytane do profilu (tekst, umiejętności, wektor).
  Bez tego profil ukraińskiej kandydatki założony z jej CV zostawał z samym
  imieniem i kontaktem. Ochrona zostaje w pozostałych przypadkach: mail
  dopasowany po wątku albo temacie i dopasowanie po tym samym pliku (SHA-256)
  dalej dają `identity_unreadable_not_primary`. Kwarantanna tożsamości
  (`is_quarantined`) działa także przy `identity_proven`.
- **Naprawa danych**: `python -m app.cli.m365_unreadable_name_rematch`
  (próba na sucho → `--apply --expected <odcisk>`, paragon w `app_settings`).
  Odpina maile `smart_name`/`smart_thread` takich osób, dopasowuje je obecnym
  matcherem, zwalnia załączniki do kolejki odczytu CV i miękko usuwa cudze CV
  z profilu.
  Odpięty mail prywatny (`is_private_filtered`) albo ze skrzynki osoby bez
  dostępu do poczty kandydatów (`eligible_m365_owner`) matchera nie widzi
  i zostaje niedopasowany — te same warunki co zwykły rematch
  (`microsoft365_sync._rematch_pass`, audyt 21.10.2026). Każde nowe miejsce,
  które przypina maile matcherem, bierze oba warunki.
