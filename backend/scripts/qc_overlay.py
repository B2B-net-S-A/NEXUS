"""Nakładka kodu z gałęzi na obraz produkcyjny — pomiar QC przed merge'em.

Uruchamiane LOKALNIE. Wypisuje na stdout jeden skrypt dla
`docker exec -i <backend> python -`: najpierw importuje podane moduły z obrazu
(stare wersje zostają w `QC_OVERLAY_BASE`), potem wykonuje pliki z gałęzi
jako te same moduły (w podanej kolejności), na końcu treść skryptu pomiaru.
W kontenerze nic się nie zapisuje — kod idzie przez stdin.

Reguła (docs/claude/rekrutacja-tablica/qc-mowi-prawde.md): przed podbiciem
`cv_qc.QC_VERSION` porównaj liczby starego i nowego kodu na tych samych
parach. Gałąź musi stać na commicie wdrożonym na produkcji plus zmiana —
inaczej nakładka wnosi też cudze zmiany.

Użycie (z katalogu backend/):
    python3 scripts/qc_overlay.py scripts/qc_truth_audit.py \\
        app/services/money_text.py app/services/cv_qc.py \\
      | ssh … "docker exec -i <backend> python -"
"""

import base64
import sys
from pathlib import Path

_PRELUDE = """
import base64 as _b64
import importlib as _il
import sys as _sys
import types as _types

QC_OVERLAY_BASE = {}
for _name, _src in _QC_OVERLAY:
    QC_OVERLAY_BASE[_name] = _il.import_module(_name)
for _name, _src in _QC_OVERLAY:
    _parent, _, _child = _name.rpartition(".")
    _mod = _types.ModuleType(_name)
    _mod.__file__ = f"<nakładka {_name}>"
    _mod.__package__ = _parent
    # Przed `exec`: `@dataclass` szuka modułu w `sys.modules`.
    _sys.modules[_name] = _mod
    exec(compile(_b64.b64decode(_src).decode(), _mod.__file__, "exec"), _mod.__dict__)
    setattr(_il.import_module(_parent), _child, _mod)
"""


def _module_name(path: Path) -> str:
    return ".".join(path.with_suffix("").parts)


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit(__doc__)
    script, *modules = (Path(a) for a in argv)
    pairs = [
        (_module_name(m), base64.b64encode(m.read_bytes()).decode()) for m in modules
    ]
    out = [f"_QC_OVERLAY = {pairs!r}", _PRELUDE, script.read_text()]
    sys.stdout.write("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1:])
