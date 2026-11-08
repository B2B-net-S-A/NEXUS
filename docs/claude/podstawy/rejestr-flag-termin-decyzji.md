# Rejestr flag domyślnie wyłączonych · termin decyzji 60 dni, strażnik w CI

Audyt z 07.11.2026 (pozycja D3). Przełącznik `bool = False` w `config.py` musi
mieć właściciela decyzji, bo inaczej funkcja za flagą starzeje się niewidocznie.

- **Nowa flaga domyślnie wyłączona** dostaje wpis w `REGISTERED_FLAGS`
  (`backend/app/core/feature_flag_registry.py`): `purpose`, `decided`, `expires`
  najwyżej 60 dni po `decided`. Bez wpisu pada
  `tests/test_feature_flag_registry.py`.
- **Po terminie** ten sam test pada na każdym PR-ze. Wyjścia: włączyć na stałe
  (domyślnie `True`), usunąć flagę z kodem albo wpisać nową datę decyzji.
- Rejestr nie przełącza niczego na produkcji. Zmianę tam robi wyłącznie workflow
  „Coolify set env”, a o włączeniu flag decyduje Artur.
- `OFF_BEFORE_REGISTRY` to stan z 08.11.2026 bez terminów, celowo: 85 dat naraz
  zablokowałoby kolejkę. Nazwa stamtąd przechodzi do rejestru przy pierwszej
  decyzji o tej fladze.
