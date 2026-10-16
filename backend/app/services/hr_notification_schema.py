"""„Ludzie w NEXUSIE” — typy powiadomień modułów kadrowych (migracja 0453).

Jedno źródło wartości ``notificationtype`` dla migracji
``0453_hr_notifications`` i testu lustra ``entrypoint.sh`` (tam stoją
literalnie w ``_ENUM_STATEMENTS``, bo ta lista powstaje przed importami).

Typy osobiste (``PERSONAL_TYPES``) trafiają do odbiorcy wybranego przez regułę
modułu (przełożony, zastępca, Kadry, posiadacz „Sprzętu”), a nie przez sekcję
produktu — „Pracownik” nie ma żadnej sekcji, a musi dostać decyzję o urlopie.
Treść nigdy nie zdradza rodzaju nieobecności osobom spoza kręgu
osoba/przełożony/Kadry ani kwot w tytule.
"""

from __future__ import annotations

#: Osobiste: odbiorcę wybiera reguła modułu; widoczne bez sekcji produktu.
PERSONAL_TYPES: tuple[str, ...] = (
    "hr_leave_requested",  # nowy wniosek → akceptujący
    "hr_leave_decided",  # akceptacja / odrzucenie → osoba
    "hr_leave_cancelled",  # anulowanie → akceptujący, zastępca, osoba
    "hr_leave_substitute",  # „zastępujesz X od … do …” → zastępca
    "hr_absence_reported",  # L4 / nieobecność zgłoszona → przełożony i Kadry
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
)

#: Opieka nad konsultantem — link do kontraktu, sekcja Delivery.
DELIVERY_TYPES: tuple[str, ...] = ("care_contact_due",)

NOTIFICATION_TYPES: tuple[str, ...] = (*PERSONAL_TYPES, *DELIVERY_TYPES)

ENUM_DDL: tuple[str, ...] = tuple(
    f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'"
    for value in NOTIFICATION_TYPES
)
