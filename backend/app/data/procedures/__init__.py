"""Procedury (SOP) utrzymywane w repozytorium, a nie tylko w bazie.

Moduł Pomoc → Procedury trzyma treść w tabeli ``procedures`` i pozwala ją
edytować adminowi z poziomu aplikacji. Dla większości procedur to wystarcza:
opisują pracę ludzi, więc autorem i właścicielem treści jest człowiek.

Instrukcja obsługi zamówień jest inna: opisuje ZACHOWANIE SYSTEMU (co wypełni
się samo z PDF-a, kiedy przyjdzie alert, czego nie wolno wpisać ręcznie), więc
dezaktualizuje się nie wtedy, gdy zmieni się proces w firmie, tylko wtedy, gdy
ktoś zmieni kod. Nikt nie pamięta, żeby po zmianie parsera wejść do Pomocy
i poprawić akapit — a błędna instrukcja jest gorsza od żadnej, bo Delivery
Lead działa według niej bez sprawdzania.

Stąd ten moduł. Treść mieszka w pliku ``.md`` w repo (widać ją w diffie PR-a),
a do bazy trafia dwoma kanałami: migracją i safety-netem w ``entrypoint.sh``
— tak jak każdy inny seed, bo alembic na produkcji bywa osierocony.

``ORDERS_LOGIC_SOURCES`` + ``orders_procedure_stamp.json`` to druga połowa
mechanizmu: lista plików, których zmiana ma wymusić przegląd instrukcji, wraz
z ich odciskiem z chwili ostatniego przeglądu. Pilnuje tego test
``tests/test_orders_procedure_freshness.py``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

#: Katalog ``backend/`` — punkt odniesienia dla ścieżek backendowych.
BACKEND_ROOT = _THIS_DIR.parents[2]

#: Katalog główny repozytorium — potrzebny, bo część obserwowanych plików
#: leży we froncie (to tam użytkownik widzi etykiety pól i przyciski, więc
#: zmiana formularza dezaktualizuje instrukcję dokładnie tak samo jak zmiana
#: reguły w API).
REPO_ROOT = BACKEND_ROOT.parent


@dataclass(frozen=True)
class SeededProcedure:
    """Procedura, której treść jest utrzymywana w repozytorium."""

    slug: str
    title: str
    sort_order: int
    filename: str

    @property
    def path(self) -> Path:
        return _THIS_DIR / self.filename

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")


ORDERS_PROCEDURE = SeededProcedure(
    slug="zamowienia-instrukcja-delivery-lead",
    title="Zamówienia — instrukcja dla Delivery Leada",
    # Lista procedur jest sortowana malejąco po `sort_order`, więc wyższa
    # liczba = wyżej. 100 zostawia miejsce na procedury, które ktoś zechce
    # wypchnąć jeszcze wyżej, bez przenumerowywania istniejących.
    sort_order=100,
    filename="zamowienia-instrukcja-delivery-lead.md",
)


#: Pliki, w których mieszka logika procesu zamówień. Zmiana KTÓREGOKOLWIEK
#: z nich każe przejrzeć instrukcję, zanim zmiana trafi na produkcję.
#:
#: Ścieżki są względne wobec katalogu repozytorium. Lista jest jawna, a nie
#: budowana globem po nazwie: glob po ``*order*`` przegapiłby
#: ``dl_alerts_scanner`` (powiadomienia o kończącym się zamówieniu) i
#: ``ezdrowie`` (wymagana część umowy), a złapałby pliki, których instrukcja
#: nie opisuje. Przenosisz plik — przenieś też wpis; test to wymusi, bo
#: nieistniejąca ścieżka jest błędem, nie pominięciem.
ORDERS_LOGIC_SOURCES: tuple[str, ...] = (
    # ── API: dodawanie, edycja i odczyt PDF zamówienia ──────────────────
    "backend/app/api/client_orders.py",
    "backend/app/api/client_order_groups.py",
    # ── Odczyt dokumentu i polityki per klient ──────────────────────────
    "backend/app/services/order_pdf_parser.py",
    # Rejestr polityk per klient: która reguła u kogo, w jakiej kolejności
    # i jak zmienia wywołanie parsera. Dołożenie klienta zmienia ten plik.
    "backend/app/services/order_policies/registry.py",
    # Warstwy per klient (korpus 09.2026) i klocki wspólne — każda zmiana
    # regexu zmienia to, co instrukcja obiecuje o odczycie u danego klienta.
    "backend/app/services/order_policies/_shared.py",
    "backend/app/services/order_policies/alior.py",
    "backend/app/services/order_policies/bank_pocztowy.py",
    "backend/app/services/order_policies/cardif.py",
    "backend/app/services/order_policies/credit_agricole.py",
    "backend/app/services/order_policies/kir.py",
    "backend/app/services/order_policies/mleasing.py",
    "backend/app/services/order_policies/nordea.py",
    "backend/app/services/order_policies/pko_bp.py",
    "backend/app/services/order_policies/velobank.py",
    "backend/app/services/order_policies/known_clients.py",
    # Rozpoznanie klienta z treści PDF i tekst zamówienia z metadanymi
    # (re-ekstrakcja przy literowaniu spacjami, cap OCR).
    "backend/app/services/order_client_identity.py",
    "backend/app/services/order_document_text.py",
    # Zamówienia z maila: pobieranie ze skrzynki kopii, sloty dobowe, dziennik.
    "backend/app/services/order_mail_ingest.py",
    "backend/app/tasks/order_mail_ingest.py",
    "backend/app/api/admin_order_mail.py",
    # Limit 10 stron OCR i komunikat o nieczytelnym skanie — instrukcja
    # podaje oba wprost, a plik zmienia się rzadko.
    "backend/app/services/cv_text_extractor.py",
    "backend/app/services/nordea_order_import.py",
    "backend/app/services/cyfrowy_polsat_orders.py",
    "backend/app/services/lotte_wedel_orders.py",
    "backend/app/services/ezdrowie.py",
    # ── Rodzaje zamówień i ich rozliczanie ──────────────────────────────
    "backend/app/services/order_types.py",
    "backend/app/services/multi_consultant_orders.py",
    "backend/app/services/cost_orders.py",
    "backend/app/services/shared_md_orders.py",
    "backend/app/services/client_order_lines.py",
    "backend/app/services/md_import_parser.py",
    # Import zużycia MD i rozliczeń kosztowych: to on decyduje, czy wiersz
    # z arkusza w ogóle zejdzie z budżetu, a instrukcja opisuje jego trzy
    # wyniki dopasowania i wymóg numeru w kolumnie „Uwagi".
    "backend/app/api/md_consumption.py",
    "backend/app/services/finance_order_matching.py",
    # ── Cykl życia zamówienia ───────────────────────────────────────────
    "backend/app/services/order_group_lifecycle.py",
    "backend/app/services/order_group_materializer.py",
    "backend/app/services/order_rate_snapshots.py",
    "backend/app/services/contract_order_offboarding.py",
    "backend/app/models/client_order.py",
    "backend/app/models/client_order_group.py",
    # ── Powiadomienia o kończącym się zamówieniu ────────────────────────
    "backend/app/services/dl_alerts.py",
    "backend/app/tasks/dl_alerts_scanner.py",
    "backend/app/tasks/dl_portal_expiry_scanner.py",
    "backend/app/tasks/contract_alerts.py",
    # ── Ekrany, na których Delivery Lead to widzi ───────────────────────
    "frontend/src/components/OrdersAndContractsTab.tsx",
    "frontend/src/components/EditOrderDialog.tsx",
    "frontend/src/components/ExtendOrderDialog.tsx",
    "frontend/src/components/NewContractorOrderDialog.tsx",
    "frontend/src/components/OrderDocumentsSection.tsx",
    "frontend/src/components/orders/InlineOrderFields.tsx",
    "frontend/src/components/orders/OrderTypeSwitch.tsx",
    "frontend/src/components/client-profile/orders/MultiConsultantOrdersTab.tsx",
    "frontend/src/components/client-profile/orders/OrderGroupFormModal.tsx",
    "frontend/src/components/client-profile/orders/ExtendOrderGroupModal.tsx",
    "frontend/src/components/client-profile/orders/EndOrderGroupModal.tsx",
    "frontend/src/components/client-profile/orders/NordeaOrderImportPanel.tsx",
    "frontend/src/lib/order-extraction.ts",
)

STAMP_PATH = _THIS_DIR / "orders_procedure_stamp.json"


def digest_of(relative_path: str) -> str:
    """SHA-256 pliku z listy obserwowanych, albo ``"missing"``.

    Brak pliku NIE jest wyjątkiem: chcemy, żeby test pokazał ``missing``
    obok nazwy przeniesionego pliku, zamiast wywalić się stack trace'em,
    z którego nie widać, o którą pozycję listy chodzi.
    """
    path = REPO_ROOT / relative_path
    if not path.is_file():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_digests() -> dict[str, str]:
    """Odciski obserwowanych plików w bieżącym drzewie."""
    return {relative: digest_of(relative) for relative in ORDERS_LOGIC_SOURCES}


def load_stamp() -> dict:
    """Zapisany stan z ostatniego przeglądu instrukcji."""
    return json.loads(STAMP_PATH.read_text(encoding="utf-8"))


def write_stamp(reviewed_at: date, digests: dict[str, str]) -> None:
    """Zapisz nowy stempel (używane przez ``scripts/stamp_orders_procedure.py``)."""
    payload = {
        "reviewed_at": reviewed_at.isoformat(),
        "sources": dict(sorted(digests.items())),
    }
    STAMP_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
