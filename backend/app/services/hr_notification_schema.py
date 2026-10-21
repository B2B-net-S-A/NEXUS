"""„Ludzie w NEXUSIE” — typy powiadomień modułów kadrowych (migracja 0457).

Jedno źródło wartości ``notificationtype`` dla migracji
``0457_hr_notifications`` i testu lustra ``entrypoint.sh`` (tam stoją
literalnie w ``_ENUM_STATEMENTS``, bo ta lista powstaje przed importami).

Typy osobiste (``PERSONAL_TYPES``) trafiają do odbiorcy wybranego przez regułę
modułu (przełożony, zastępca, Kadry, posiadacz „Sprzętu”), a nie przez sekcję
produktu — „Pracownik” nie ma żadnej sekcji, a musi dostać decyzję o urlopie.
Treść nigdy nie zdradza rodzaju nieobecności osobom spoza kręgu
osoba/przełożony/Kadry ani kwot w tytule.
"""

from __future__ import annotations

from app.services.care_board_schema import NOTIFICATION_TYPES as CARE_BOARD_TYPES
from app.services.client_structure_schema import (
    NOTIFICATION_TYPES as CLIENT_STRUCTURE_TYPES,
)
from app.services.hr_agreements_schema import NOTIFICATION_TYPES as AGREEMENT_TYPES
from app.services.hr_approval_settlement_schema import (
    NOTIFICATION_TYPES as APPROVAL_SETTLEMENT_TYPES,
)
from app.services.hr_approvals_schema import NOTIFICATION_TYPES as APPROVAL_TYPES
from app.services.hr_settlement_schema import NOTIFICATION_TYPES as SETTLEMENT_TYPES

#: Osobiste: odbiorcę wybiera reguła modułu; widoczne bez sekcji produktu.
PERSONAL_TYPES: tuple[str, ...] = (
    "hr_leave_requested",  # nowy wniosek → akceptujący
    "hr_leave_decided",  # akceptacja / odrzucenie → osoba
    "hr_leave_cancelled",  # anulowanie → akceptujący, zastępca, osoba
    "hr_leave_substitute",  # „zastępujesz X od … do …” → zastępca
    "hr_absence_reported",  # L4 / nieobecność zgłoszona → przełożony i Kadry
    "hr_leave_conflict",  # koordynator zgłasza kolizję z przerwą B2B/zlecenia → osoba
    "hr_timesheet_submitted",  # timesheet do akceptacji → akceptujący
    "hr_timesheet_decided",  # zaakceptowany / zwrócony / cofnięty → osoba
    "hr_timesheet_reminder",  # 1.–5. dnia: brak wysłanego timesheetu
    "hr_bonus_assigned",  # premia przyznana / zmieniona / anulowana → osoba
    "hr_rate_changed",  # zmiana stawki → osoba
    "hr_lifecycle_task",  # zadanie z wejścia / odejścia → wykonawca
    "hr_work_handover",  # przekazana praca odchodzącej osoby → przejmujący
    "admin_case_assigned",  # sprawa administracja@ przypisana → osoba
    "equipment_task",  # „Do zrobienia” recepcji (wydanie, zwrot, protokół)
    "equipment_protocol_signed",  # protokół podpisany przez odbierającego
    "equipment_return_reminder",  # „Przypomnij” o zwrocie → posiadacz (0479)
    # „Przekaż do front office” → head pionu front office, HoR, Delivery Leadzi.
    "care_front_office_handoff",
    # Komunikat do konsultantów: do zatwierdzenia → head back office / admin,
    # decyzja → autor, odbity mail → opiekun („popraw e-mail”).
    "care_announcement",
    # Rozliczenia zespołu (etap 4) — wartości enuma dodaje migracja 0467.
    *SETTLEMENT_TYPES,
    # Umowy z ludźmi (etap 5) — stan umowy do osoby z Kadr; enum dodaje 0469.
    *AGREEMENT_TYPES,
    # Zgody na wydatki i premie poza umową — do decydującego i do autora (0483).
    *APPROVAL_TYPES,
    # Rozliczenie zgód — dopłata do zatwierdzającego, odnowienie subskrypcji (0486).
    *APPROVAL_SETTLEMENT_TYPES,
)

#: Opieka nad konsultantem — link do kontraktu, sekcja Delivery; struktura
#: u klienta (0475) — „uzupełnij strukturę klienta X” do Delivery Leadów;
#: popyt z rozmowy opiekuna (0504) — „klient zatrudnia” do DL klienta.
DELIVERY_TYPES: tuple[str, ...] = (
    "care_contact_due",
    *CLIENT_STRUCTURE_TYPES,
    *CARE_BOARD_TYPES,
)

NOTIFICATION_TYPES: tuple[str, ...] = (*PERSONAL_TYPES, *DELIVERY_TYPES)

ENUM_DDL: tuple[str, ...] = tuple(
    f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'"
    for value in NOTIFICATION_TYPES
)
