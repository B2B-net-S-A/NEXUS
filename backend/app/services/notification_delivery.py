"""Admin-controlled routine email delivery. Missing policy is deliberately OFF.

Activation establishes a server timestamp; an event from an earlier disabled
period can never be replayed. In-app notifications and account-security email
are independent. This module never grants provider access or sends test mail.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from sqlalchemy import DateTime, and_, cast, create_engine, or_, select, text, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.app_setting import AppSetting
from app.services.hr import program as hr_program

logger = logging.getLogger(__name__)
SETTING_KEY = "notification_email_delivery"
_send_local = threading.local()

CATALOG = (
    dict(
        id="chat_unread",
        label="Nieprzeczytane wiadomości czatu",
        module="Czat",
        trigger="Nieprzeczytana wiadomość lub wzmianka; adresat jest offline od co najmniej 15 minut.",
        recipient_rule="Adresat powiadomienia czatu, nadal aktywny i uprawniony do jego sekcji.",
    ),
    dict(
        id="mentions",
        label="Wzmianki w notatkach",
        module="Notatki i screening",
        trigger="Oznaczenie osoby przez @wzmiankę w nowej lub edytowanej notatce.",
        recipient_rule="Oznaczone aktywne osoby z aktualnym dostępem do sekcji.",
    ),
    dict(
        id="pipeline_stage",
        label="Zmiany etapów rekrutacji",
        module="Rekrutacje",
        trigger="Zmiana etapu spełniająca skonfigurowaną regułę powiadomień.",
        recipient_rule="Odbiorcy reguły etapu: rekruter, DL, TAC, wskazana osoba, rola lub twórca kandydata. Nadal obowiązują szczegółowe reguły etapów.",
    ),
    dict(
        id="rate_change",
        label="Wzrost stawki kandydata po wysłaniu CV",
        module="Rekrutacje",
        trigger="Kandydat, którego CV jest już u klienta, chce wyższej stawki (zapis w debriefie, panelu osoby albo profilu).",
        recipient_rule="Delivery Lead rekrutacji (bez niego: Delivery Leadzi z portfela klienta), aktywny i z dostępem do sekcji Pipeline.",
    ),
    dict(
        id="job_deadline",
        label="Terminy rekrutacji",
        module="Rekrutacje",
        trigger="Zbliżający się termin otwartej rekrutacji: progi 7, 3 i 1 dzień zgodnie z konfiguracją skanera.",
        recipient_rule="Przypisany rekruter, Delivery Lead, TAC i aktywni współpracownicy rekrutacji, z aktualnym dostępem.",
    ),
    dict(
        id="delivery_alert",
        label="Alerty klientów i umów",
        module="Klienci i umowy",
        trigger="Nowy alert lub próg przypomnienia z włączonym kanałem email w regule alertu.",
        recipient_rule="Delivery Leadzi przypisani do danego klienta, aktywni i z dostępem do sekcji (bez administratorów).",
    ),
    dict(
        id="application_confirmation",
        label="Potwierdzenie aplikacji",
        module="Strona kariery",
        trigger="Kandydat wysłał zgłoszenie z CV przez link aplikacyjny lub stronę kariery (najwyżej jeden mail na adres i link w ciągu 24 h).",
        recipient_rule="Kandydat — adres z formularza. Treść jest taka sama, niezależnie od tego, czy osoba była już w bazie.",
    ),
    # Maile natychmiast (07.10.2026) — kolejka `tasks/notification_email_outbox.py`
    # bierze powiadomienia z dzwonka typów z `notification_kind`.
    dict(
        id="dl_review",
        label="CV czeka na Twój przegląd",
        module="Rekrutacje",
        trigger="Rekruter przekazał kandydata do „QC CV” (albo do kolejki Cpro u Nordei); "
        "po imporcie z Traffita — kandydaci, którzy nadal stoją w kolejce Cpro.",
        recipient_rule="Delivery Lead rekrutacji (bez niego: Delivery Leadzi z portfela klienta); osoba od Cpro.",
    ),
    dict(
        id="cv_returned",
        label="CV wróciło do poprawy",
        module="Rekrutacje",
        trigger="Delivery Lead cofnął kandydata z „QC CV” albo z kolejki Cpro; "
        "QC CV nie przeszło po przekazaniu kandydata do „QC CV”.",
        recipient_rule="Osoba, która przekazała kartę, i rekruter kandydata.",
    ),
    dict(
        id="request_assigned",
        label="Nowa rekrutacja dla Ciebie",
        module="Rekrutacje",
        trigger="Ktoś (albo automat przydziału) przypisał Cię do prowadzenia rekrutacji.",
        recipient_rule="Nowo przypisana osoba; bez maila do osoby, która przypisała samą siebie.",
    ),
    # Mail obowiązkowy (26.10.2026) — `services/client_job_opened.py`.
    dict(
        id="client_job_opened",
        label="Nowa rekrutacja u Twojego klienta",
        module="Rekrutacje",
        trigger="Założenie albo ponowne otwarcie rekrutacji u Twojego klienta, "
        "także przez Ciebie. Kilka w ciągu 10 minut przychodzi jednym mailem.",
        recipient_rule="Delivery Lead rekrutacji (bez niego: Head of Recruitment). "
        "W mailu: rekrutacja, klient, data otwarcia i kto ją prowadzi.",
    ),
    # Mail obowiązkowy (27.10.2026) — `services/job_ad/reminders.py`.
    dict(
        id="job_ad_reminders",
        label="Brakujące ogłoszenia rekrutacji",
        module="Rekrutacje",
        trigger="Codziennie rano w dni robocze, dopóki otwarta rekrutacja nie wisi "
        "na stronie kariery, Pracuj.pl albo JustJoin.IT (i nikt nie zapisał „nie "
        "publikujemy”). Rekrutacje sprzed startu przypomnień — jednym mailem "
        "zbiorczym. Także prośba Delivery Leada o stronę kariery.",
        recipient_rule="Strona kariery: Rekruter rekrutacji (bez niego DL). "
        "Pracuj.pl i JustJoin.IT: Delivery Lead (bez niego Head of Recruitment). "
        "DL widzi w mailu wszystkie trzy kanały swojej rekrutacji.",
    ),
    # Mail obowiązkowy (27.10.2026) — `services/job_p0.py`.
    dict(
        id="job_p0",
        label="P0 na rekrutacji",
        module="Rekrutacje",
        trigger="Head of Recruitment albo administrator ustawił rekrutacji P0 — "
        "ultrapilne przez 24 h (48 h albo do piątku), z powodem.",
        recipient_rule="Rekruterzy pracujący nad rekrutacją i jej Delivery Lead, "
        "bez osoby, która ustawiła P0. W mailu: rekrutacja, klient, powód i termin.",
    ),
    # Mail obowiązkowy (28.10.2026) — `services/job_closed_notices.py`.
    dict(
        id="job_closed",
        label="Rekrutacja zamknięta — Twoje osoby czekają",
        module="Rekrutacje",
        trigger="Ktoś zamknął rekrutację, w której Twoje osoby stoją w „CV wysłane”, "
        "„Rozmowie u klienta” albo „Umowie”. Automaty (Traffit, scalanie, "
        "stare szkice) nie wysyłają.",
        recipient_rule="Rekruter osoby: ten, kto ją zweryfikował, a bez weryfikacji "
        "ten, kto ją dodał; bez osoby, która zamknęła. W mailu: rekrutacja, klient, "
        "powód zamknięcia i lista osób.",
    ),
    # Mail obowiązkowy (28.10.2026) — `services/departure_care.py`.
    dict(
        id="departed_care",
        label="Kandydaci po osobie, która odeszła",
        module="Rekrutacje",
        trigger="Konto rekrutera zostało wyłączone (odejście z firmy), a w Twoich "
        "rekrutacjach zostali jego kandydaci. Przypomnienie po 5 dniach roboczych, "
        "gdy coś jeszcze nie jest domknięte.",
        recipient_rule="Delivery Lead rekrutacji; bez niego główny Delivery Lead "
        "klienta, a bez niego Head of Recruitment. W mailu: kto odszedł, ile osób "
        "w ilu rekrutacjach i na jakich etapach.",
    ),
    # Maile natychmiast (22.10.2026, „brak maila o terminach rozmów”) — typy
    # dzwonka z `BELL_MAIL_TYPES`, treść = tytuł i opis wpisu w dzwonku.
    dict(
        id="client_interview",
        label="Rozmowy u klienta",
        module="Rekrutacje",
        trigger="Terminy od klienta do ustalenia z kandydatem, kandydat wybrał termin, "
        "termin potwierdzony u klienta albo zmieniony, rozmowa przełożona albo "
        "odwołana, zapisany debrief; 15 minut po rozmowie — prośba o telefon do kandydata.",
        recipient_rule="Rekruter kandydata, Delivery Lead rekrutacji i właściciel "
        "wydarzenia w kalendarzu — każdy przy kroku, który na niego czeka; bez autora zmiany.",
    ),
    dict(
        id="prep_change",
        label="Prep: odmowa albo zmiana terminu",
        module="Rekrutacje",
        trigger="Kandydat odmówił prepu albo proponuje inny termin; ktoś z pary "
        "zaplanował, przełożył, odwołał albo zmienił zaproszonych na prep "
        "w Twoim kalendarzu.",
        recipient_rule="Odmowa i inny termin: cała para (Delivery Lead, rekruter, "
        "planujący) bez autora; zmiana prepu: prowadzący, w którego kalendarzu "
        "stoi spotkanie.",
    ),
    dict(
        id="client_accepted",
        label="Klient zaakceptował kandydata",
        module="Rekrutacje",
        trigger="Karta weszła na etap „Akceptacja” — dalej oferta i umowa.",
        recipient_rule="Rekruter kandydata, prowadzący, Delivery Lead rekrutacji "
        "i Head of Recruitment, bez osoby, która zaznaczyła akceptację.",
    ),
    dict(
        id="pre_contract",
        label="Umowa przedwstępna",
        module="Rekrutacje",
        trigger="Prośba o umowę przedwstępną, wystawienie, podpisy, wygasanie, "
        "rezygnacja kandydata i termin umowy B2B.",
        recipient_rule="Wystawiający i osoby, które o umowę poprosiły albo ją "
        "obserwują; bez autora zmiany.",
    ),
    dict(
        id="team_task",
        label="Zadania od zespołu",
        module="Rekrutacje",
        trigger="Ktoś wytypował Cię do wysłania osoby do Cpro, odpowiedział na "
        "Twoją notatkę albo przejął Twoją osobę w „Nowych”.",
        recipient_rule="Wytypowana osoba, autor notatki, rekruter, któremu przejęto kartę.",
    ),
    dict(
        id="hire_documents",
        label="Zatrudniony bez zamówienia albo umowy",
        module="Klienci i umowy",
        trigger="Podpis umowy przeniósł osobę na „Zatrudniony”, a od klienta nie ma "
        "zamówienia; ręczne „Potwierdź zatrudnienie” bez umowy w Kontraktach.",
        recipient_rule="Brak zamówienia — Finanse; brak umowy — Delivery Leadzi klienta.",
    ),
    dict(
        id="signature_request",
        label="Prośba o potwierdzenie podpisu umowy",
        module="Klienci i umowy",
        trigger="Rekruter prosi o oznaczenie umowy B2B z Generatora jako podpisanej (najwyżej raz na dobę).",
        recipient_rule="Delivery Lead rekrutacji, potem Delivery Leadzi z portfela klienta, potem TCM — z uprawnieniem „Podpis B2B”.",
    ),
    dict(
        id="system_failure",
        label="Awaria automatu",
        module="System",
        trigger="Ten sam automat (przegląd bazy, propozycje, auto-CV) padł 3 razy z rzędu; "
        "DL albo rekruter jest poza grupą, w której aplikacja zakłada prepy w Teams "
        "(najwyżej raz dziennie).",
        recipient_rule="Aktywni administratorzy.",
    ),
    # 0508 (22.10.2026): alarm bez blokady — `services/candidate_data_access_alerts.py`.
    dict(
        id="data_access_alert",
        label="Masowe przeglądanie CV",
        module="System",
        trigger="Ktoś otworzył pliki ponad 40 kandydatów w godzinę, zapisał na dysk "
        "ponad 25 plików albo wyeksportował ponad 200 osób w ciągu dnia (konto "
        "młodsze niż 14 dni — progi o połowę niższe); 3 nowe konta otwierają CV "
        "w tej samej godzinie. Najwyżej jeden alarm dziennie na osobę.",
        recipient_rule="Aktywni administratorzy i Head of Recruitment.",
    ),
    # 0612 (28.10.2026): nowa osoba po pierwszym logowaniu — `services/new_person_setup.py`.
    dict(
        id="new_person",
        label="Nowa osoba w NEXUSIE",
        module="System",
        trigger="Ktoś zalogował się pierwszy raz przez Microsoft i dostał konto "
        "„Konsultant/Kontraktor”. Zdecyduj, czy to rekruter (rola, kategorie "
        "kompetencji, przełożony), czy zostaje konsultantem.",
        recipient_rule="Aktywni administratorzy i Head of Recruitment.",
    ),
    # „Ludzie w NEXUSIE” (17.10.2026) — typy `HR_MAIL_TYPES`, treść składa
    # `services/hr/hr_mail.py` (bez rodzaju nieobecności i bez kwot).
    dict(
        id="hr_people",
        label="Czas i ludzie",
        module="Ludzie",
        trigger="Wniosek o nieobecność do decyzji i decyzja o nim, anulowana albo "
        "zgłoszona nieobecność (na B2B i zleceniu: zgłoszona przerwa i kolizja "
        "zgłoszona przez koordynatora), zastępstwo, raport godzin wysłany do "
        "akceptacji, zaakceptowany, zwrócony albo niewysłany w terminie, przekazana praca, zadania wejścia "
        "i odejścia, sprawa administracja@, zadania sprzętu, podpisany protokół "
        "i konsultant przekazany z opieki do front office, zgoda na wydatek albo premię "
        "poza umową do decyzji i decyzja o niej.",
        recipient_rule="Osoba, na którą sprawa czeka: akceptujący wniosku (przełożony "
        "albo Kadry), koordynator osoby na B2B i zleceniu, wnioskodawca, zastępca, "
        "przejmujący pracę, wykonawca zadania, "
        "przypisany do sprawy, osoby z uprawnieniem „Sprzęt”, a przy przekazaniu do "
        "front office: head pionu front office, Head of Recruitment i Delivery "
        "Leadzi, przy zgodzie — przełożony autora albo zatwierdzający z Ustawień. W mailu "
        "nie ma rodzaju nieobecności ani kwot — poza mailem do decydującego o zgodzie "
        "(kwota i „po co”, decyzja Artura 20.10.2026).",
    ),
    # Mail obowiązkowy (26.10.2026) — treść składa `services/hr/hr_mail.py`.
    dict(
        id="hr_bonus",
        label="Masz nową premię",
        module="Ludzie",
        trigger="Płace przyznały, zmieniły albo anulowały Ci premię (na B2B "
        "i zleceniu: wynagrodzenie dodatkowe), także premię poza umową po zgodzie.",
        recipient_rule="Osoba, której premia dotyczy. W mailu: za co i za który "
        "miesiąc, bez kwoty (decyzja Artura 26.10.2026); kwota jest w „Moim czasie”.",
    ),
    # Poranny skrót (07.10.2026) — `tasks/daily_digest_email.py`.
    dict(
        id="daily_digest",
        label="Poranny skrót „Twój dzień w NEXUSIE”",
        module="Pulpit",
        trigger="Dzień roboczy od 8:00 — to, co czeka na osobę w panelu „Czeka na Ciebie”. Pusty skrót nie wychodzi.",
        recipient_rule="Aktywni rekruterzy, TCM, Delivery Leadzi, Head of Recruitment i Finanse (rola główna albo dodatkowa). Admin bez tych ról — nie.",
    ),
    # Raporty KPI mailem (plan PR3, 23.09.2026) — `tasks/kpi_email_reports.py`.
    dict(
        id="kpi_weekly_report",
        label="Tygodniowy raport KPI zespołu",
        module="Statystyki",
        trigger="Poniedziałek od 8:00 — KPI zespołu za zamknięty tydzień (weryfikacje, rekomendacje, placementy, nowi kandydaci).",
        recipient_rule="Aktywni Head of Recruitment (rola główna albo dodatkowa) z dostępem do sekcji Insights; zespół według zakresu pulpitu odbiorcy.",
    ),
    dict(
        id="board_monthly_report",
        label="Miesięczne podsumowanie Rady",
        module="Statystyki",
        trigger="1. dzień roboczy miesiąca od 8:00 — kokpit Rady i porównanie rok do roku za zamknięty miesiąc.",
        recipient_rule="Aktywne konta z uprawnieniem „Moduł Finanse” albo z rolą „Rada nadzorcza”, z dostępem do sekcji Insights (mail niesie przychód i marżę).",
    ),
    # Mail do Rady przy każdym placemencie (decyzja Artura 22.10.2026) —
    # `services/board_placement_alerts.py`, wysyła pętla raportów.
    dict(
        id="board_placement_alert",
        label="Nowy placement — mail do Rady",
        module="Statystyki",
        trigger="Pierwsze „Zatrudniony” pary (kandydat, rekrutacja) po dacie „wysyłaj od” — w ciągu ok. 10 minut. Jeden mail na parę; bez danych kandydata.",
        recipient_rule="Aktywne konta z rolą „Rada nadzorcza”. W mailu: klient, rekrutacja, rekruter, Delivery Lead, start, marża na godzinę, który placement w miesiącu i akceptacje w drodze.",
    ),
)
# Raporty nie mają odpowiednika w dzwonku — wychodzą wyłącznie mailem.
REPORT_KINDS = frozenset(
    {
        "kpi_weekly_report",
        "board_monthly_report",
        "board_placement_alert",
        "daily_digest",
    }
)
ROUTINE_KINDS = frozenset(item["id"] for item in CATALOG)
SECURITY_CATALOG = (
    dict(
        id="password_reset",
        label="Reset hasła",
        trigger="Żądanie resetu hasła użytkownika lub administratora.",
    ),
    dict(
        id="email_verification",
        label="Weryfikacja adresu",
        trigger="Rejestracja lub ponowienie weryfikacji adresu email.",
    ),
    dict(
        id="password_changed",
        label="Zmiana hasła",
        trigger="Zmiana hasła konta przez użytkownika lub administratora.",
    ),
)


def _datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime) or parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class DeliveryPolicy:
    enabled: bool = False
    send_not_before: datetime | None = None
    types: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: Any) -> DeliveryPolicy:
        value = value if isinstance(value, dict) else {}
        raw_types = value.get("types")
        return cls(
            enabled=value.get("enabled") is True,
            send_not_before=_datetime(value.get("send_not_before")),
            types={
                key: item
                for key, item in (raw_types or {}).items()
                if key in ROUTINE_KINDS and isinstance(item, dict)
            }
            if isinstance(raw_types, dict)
            else {},
        )

    def cutoff_for(self, kind: str) -> datetime | None:
        local = _datetime(self.types.get(kind, {}).get("send_not_before"))
        if self.send_not_before is None or local is None:
            return None
        return max(self.send_not_before, local)

    def kind_enabled(self, kind: str) -> bool:
        return bool(
            kind in ROUTINE_KINDS
            and self.enabled
            and self.types.get(kind, {}).get("email_enabled") is True
            and self.cutoff_for(kind) is not None
        )

    def paused_reason(self, kind: str) -> str | None:
        """Powód, z jakim admin wstrzymał mail obowiązkowy (`None` = nie wstrzymał)."""
        reason = self.types.get(kind, {}).get("paused_reason")
        return reason if isinstance(reason, str) and reason else None

    @property
    def effective_enabled(self) -> bool:
        return any(self.kind_enabled(kind) for kind in ROUTINE_KINDS)

    def allows(self, kind: str, event_at: datetime | None) -> bool:
        event_at = _datetime(event_at)
        cutoff = self.cutoff_for(kind)
        return bool(
            self.kind_enabled(kind) and event_at and cutoff and event_at >= cutoff
        )


HR_MAIL_KIND = "hr_people"
HR_BONUS_KIND = "hr_bonus"
CLIENT_JOB_KIND = "client_job_opened"
JOB_AD_KIND = "job_ad_reminders"
JOB_P0_KIND = "job_p0"
JOB_CLOSED_KIND = "job_closed"
DEPARTED_CARE_KIND = "departed_care"

# Maile obowiązkowe (decyzja Artura 26.10.2026): sprawy, na które ktoś czeka.
# Pomiar na kopii produkcji z 22.10: nikt z 38 kont nie wyłączył sobie maila,
# a 105 wpisów o rozmowach, akceptacjach klienta i braku zamówienia w 14 dni
# nie poszło mailem, bo tych rodzajów nikt nie włączył w Ustawieniach firmy.
# Obowiązkowy mail włącza się sam przy starcie (`ensure_required_kinds`, bez
# zaległości), konto nie może go wyłączyć sobie, a wyciszenie kategorii
# w dzwonku go nie zatrzymuje. Wstrzymać go może tylko admin dla całej firmy,
# z powodem zapisanym w polityce i w Historii zdarzeń.
REQUIRED_KINDS = frozenset(
    {
        "request_assigned",
        CLIENT_JOB_KIND,
        JOB_AD_KIND,
        JOB_P0_KIND,
        JOB_CLOSED_KIND,
        DEPARTED_CARE_KIND,
        "client_interview",
        "dl_review",
        "cv_returned",
        "client_accepted",
        "hire_documents",
        "signature_request",
        "delivery_alert",
        HR_MAIL_KIND,
        HR_BONUS_KIND,
        "data_access_alert",
        "system_failure",
    }
)
PAUSE_REASON_MAX = 500


class RequiredKindReasonMissing(ValueError):
    """Wstrzymanie maila obowiązkowego bez powodu."""


# Typy kadrowe, które idą mailem „Czas i ludzie”: sprawy, na które ktoś czeka.
# Raport godzin wysłany do akceptacji (`hr_timesheet_submitted`) idzie mailem
# od 18.10.2026 — jak w Compassie akceptujący dowiaduje się o nim od razu,
# a nie dopiero z licznika w „Akceptacjach” (od 1.11 raporty składa się
# w NEXUSIE). Premia (`hr_bonus_assigned`) ma od 26.10.2026 własny mail
# obowiązkowy „Masz nową premię” (`HR_BONUS_KIND`, bez kwoty — treść składa
# `hr_mail.bonus_mail`), więc tej listy nie dotyczy. Bez maila zostają stawki
# (kwoty) i opieka
# (`care_contact_due`, sekcja Delivery), a z rozliczeń — informacja o zapłacie
# (`hr_settlement_paid`; prośba o korektę faktury i rozliczenie do decyzji
# Płac idą mailem). Przypomnienia o terminie
# (`hr_timesheet_reminder` raz w miesiącu, zaległe zadania wejścia/odejścia
# w poniedziałek, sprzęt na najbliższe dni) idą jak „Terminy rekrutacji”.
HR_MAIL_TYPES: tuple[str, ...] = (
    "hr_leave_requested",
    "hr_leave_decided",
    "hr_leave_cancelled",
    "hr_leave_substitute",
    "hr_absence_reported",
    "hr_leave_conflict",
    "hr_timesheet_submitted",
    "hr_timesheet_decided",
    "hr_timesheet_reminder",
    "hr_lifecycle_task",
    "hr_work_handover",
    "admin_case_assigned",
    "equipment_task",
    "equipment_protocol_signed",
    "equipment_return_reminder",
    "care_front_office_handoff",
    "care_announcement",
    "hr_settlement_correction",
    "hr_settlement_review",
    "hr_agreement_update",
    # Zgody (0483): do decydującego — mail z kwotą i przyciskami
    # (`services/hr/approvals/mail.py`), decyzja do autora — bez wolnego tekstu.
    "hr_approval_requested",
    "hr_approval_decided",
    # Rozliczenie zgód (0486): dopłata do zatwierdzającego, odnowienie
    # subskrypcji do opiekuna — bez kwot i wolnego tekstu w mailu.
    "hr_approval_topup_requested",
    "hr_subscription_renewal",
)


# Rodzaj maila → typy dzwonka, które idą nim od razu (22.10.2026). Bez
# przypomnienia 15 min przed wydarzeniem (`interview_scheduled` — mail
# przyszedłby za późno), bez ponagleń po rozmowie (`post_interview_t45`,
# eskalacja) i bez zmiany prepu u kogoś innego z pary (`prep_changed`).
BELL_MAIL_TYPES: dict[str, tuple[str, ...]] = {
    "client_interview": (
        "interview_slots_requested",
        "interview_slot_chosen",
        "interview_slot_confirmed",
        "interview_changed",
        "interview_debrief_saved",
        "post_interview_t15",
    ),
    "prep_change": ("prep_candidate_declined", "prep_changed_yours"),
    "client_accepted": ("client_accepted",),
    "pre_contract": ("pre_contract",),
    "team_task": ("cpro_send_assigned", "note_reply", "candidate_claim_taken"),
    "hire_documents": ("hired_order_missing", "hire_missing_contract"),
    JOB_P0_KIND: ("job_p0_set", "job_p0_requested"),
    JOB_CLOSED_KIND: ("job_closed_people_waiting",),
    DEPARTED_CARE_KIND: ("departed_pairs_care",),
}


def notification_kind(notification_type: Any) -> str | None:
    return {
        **dict.fromkeys(HR_MAIL_TYPES, HR_MAIL_KIND),
        **{t: kind for kind, types in BELL_MAIL_TYPES.items() for t in types},
        "job_chat_message": "chat_unread",
        "job_chat_mention": "chat_unread",
        "note_mention": "mentions",
        "stage_rule": "pipeline_stage",
        "candidate_rate_change_task": "rate_change",
        "job_deadline_7d": "job_deadline",
        "job_deadline_3d": "job_deadline",
        "job_deadline_1d": "job_deadline",
        # Maile natychmiast (07.10.2026). `board_task_waiting` to także
        # „CV wróciło do poprawy” — rozróżnia `immediate_email_kind`.
        "board_task_waiting": "dl_review",
        "request_assignment_changed": "request_assigned",
        "b2b_signature_requested": "signature_request",
        "automation_failing": "system_failure",
        "teams_prep_scope_missing": "system_failure",
        "candidate_data_access_alert": "data_access_alert",
        "new_person_signed_in": "new_person",
        "client_job_opened": CLIENT_JOB_KIND,
        "job_ad_missing": JOB_AD_KIND,
        "job_ad_backlog": JOB_AD_KIND,
        "job_ad_nudge": JOB_AD_KIND,
        "hr_bonus_assigned": HR_BONUS_KIND,
    }.get(getattr(notification_type, "value", notification_type))


DIGEST_KIND = "daily_digest"
# `users.email_opt_outs[RESUMED_KEY] = {rodzaj: czas ponownego włączenia}`.
RESUMED_KEY = "_resumed"


def email_opted_out(user: Any, kind: str) -> bool:
    """Czy konto wyłączyło sobie ten mail („Maile do Ciebie”, 0427).

    Każdy nadawca pyta o to tuż przed wysyłką (strażnik:
    `test_notification_email_prefs.py`). Poranny skrót ma własną kolumnę
    (0425), reszta żyje w `users.email_opt_outs` jako `{rodzaj: czas}`.
    Wyłączony mail nie zmienia dzwonka ani zadania w „Czeka na Ciebie”.
    """
    if kind in REQUIRED_KINDS:
        # Stary wpis wyłączenia (sprzed 26.10.2026) nic już nie znaczy.
        return False
    if kind == DIGEST_KIND:
        return getattr(user, "daily_digest_email_enabled", True) is False
    raw = getattr(user, "email_opt_outs", None)
    # Wyłączenie to znacznik czasu; `_resumed` (słownik) nim nie jest.
    since = raw.get(kind) if isinstance(raw, dict) else None
    return isinstance(since, str) and bool(since)


def email_resumed_at(user: Any, kind: str) -> datetime | None:
    """Kiedy konto włączyło ten mail z powrotem (`None` = nigdy nie wyłączało)."""
    raw = getattr(user, "email_opt_outs", None)
    resumed = raw.get(RESUMED_KEY) if isinstance(raw, dict) else None
    return _datetime(resumed.get(kind)) if isinstance(resumed, dict) else None


def email_wanted(user: Any, kind: str, event_at: datetime | None) -> bool:
    """Czy konto chce mail o TYM zdarzeniu.

    Nadawcy z kolejką (dzwonek → mail) pytają tędy: zdarzenie z czasu, gdy
    mail był wyłączony, nie wychodzi po ponownym włączeniu — tak samo jak
    firmowy przełącznik nie wysyła zaległości (`send_not_before`).
    """
    if kind in REQUIRED_KINDS:
        return True
    if email_opted_out(user, kind):
        return False
    resumed = email_resumed_at(user, kind)
    event_at = _datetime(event_at)
    return resumed is None or (event_at is not None and event_at >= resumed)


def email_queue_clause(kind: str, event_column: Any) -> Any:
    """Warunek SQL kolejki: lustro `email_wanted` na złączonym `User`.

    Musi stać w zapytaniu, nie tylko w pętli: wiersze konta z wyłączonym
    mailem nigdy nie dostają stempla wysyłki, więc odsiane dopiero w Pythonie
    zajmowałyby paczkę (najstarsze pierwsze) i z czasem zatrzymały ten mail
    wszystkim innym (przegląd kodu 09.10.2026; ta sama lekcja co wyciszony
    czat w rundzie 9).
    """
    from app.models.user import User

    if kind in REQUIRED_KINDS:
        return true()
    resumed = cast(
        User.email_opt_outs[(RESUMED_KEY, kind)].astext, DateTime(timezone=True)
    )
    return and_(
        ~User.email_opt_outs.has_key(kind),
        or_(resumed.is_(None), event_column >= resumed),
    )


# Rodzaje wysyłane natychmiast przez `tasks/notification_email_outbox.py`.
IMMEDIATE_KINDS = (
    "dl_review",
    "cv_returned",
    "request_assigned",
    "signature_request",
    "system_failure",
    "data_access_alert",
    "new_person",
    HR_MAIL_KIND,
    HR_BONUS_KIND,
    CLIENT_JOB_KIND,
    JOB_AD_KIND,
    *BELL_MAIL_TYPES,
)


def immediate_email_kind(
    notification_type: Any, *, title: str | None, related_entity_type: str | None
) -> str | None:
    """Rodzaj maila natychmiast dla wiersza dzwonka albo `None` (bez maila).

    Ta sama reguła co zapytanie kolejki (`notification_email_outbox`):
    zwrot do poprawy rozpoznaje początek tytułu, a poranny skrót przydziałów
    (`request_assignment_changed` z encją `user`) nie idzie mailem — niesie
    to samo, co poranny skrót dnia.
    """
    from app.services.stage_handoff_recipients import RETURNED_TITLE_PREFIXES

    kind = notification_kind(notification_type)
    if kind not in IMMEDIATE_KINDS:
        return None
    if kind == "dl_review" and (title or "").startswith(RETURNED_TITLE_PREFIXES):
        return "cv_returned"
    if kind == "request_assigned" and related_entity_type != "job":
        return None
    return kind


async def load_policy(db: AsyncSession) -> DeliveryPolicy:
    # A fresh scalar avoids identity-map caching when an admin changes policy
    # during a long worker pass.
    value = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == SETTING_KEY)
    )
    return DeliveryPolicy.from_value(value)


@lru_cache(maxsize=1)
def _read_engine():
    return create_engine(
        make_url(settings.DATABASE_URL).set(drivername="postgresql+psycopg2"),
        pool_size=1,
        max_overflow=0,
        pool_timeout=2,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 2, "options": "-c statement_timeout=2000"},
    )


def load_policy_sync() -> DeliveryPolicy:
    with _read_engine().connect() as conn:
        value = conn.execute(
            text("SELECT value FROM app_settings WHERE key=:key"), {"key": SETTING_KEY}
        ).scalar_one_or_none()
    return DeliveryPolicy.from_value(value)


def is_delivery_allowed_sync(kind: str, event_at: datetime | None) -> bool:
    try:
        return load_policy_sync().allows(kind, event_at)
    except Exception:
        logger.warning("notification email policy unavailable; delivery blocked")
        return False


def guarded_send(kind: str, event_at: datetime | None, send, *args, **kwargs) -> bool:
    """Recheck current policy immediately before entering a synchronous sender."""
    _send_local.policy_blocked = not is_delivery_allowed_sync(kind, event_at)
    if _send_local.policy_blocked:
        return False
    return send(*args, **kwargs)


def last_send_policy_blocked() -> bool:
    return bool(getattr(_send_local, "policy_blocked", False))


def updated_value(
    previous: DeliveryPolicy,
    *,
    enabled: bool,
    toggles: dict[str, bool],
    now: datetime,
    reason: str | None = None,
) -> dict:
    """Pure transition used after locking the stored row. Never accept client cutoffs.

    Wyłączenie maila obowiązkowego wymaga powodu (`RequiredKindReasonMissing`);
    powód i chwila zostają w rodzaju, dopóki admin nie włączy go z powrotem —
    po tym znaku `ensure_required_kinds` nie włącza go sam przy starcie.
    """
    if not set(toggles) <= ROUTINE_KINDS:
        raise ValueError("unknown notification email type")
    reason = (reason or "").strip()[:PAUSE_REASON_MAX]
    global_cutoff = previous.send_not_before
    if enabled and (not previous.enabled or global_cutoff is None):
        global_cutoff = now
    types = {}
    for kind in ROUTINE_KINDS:
        old = previous.types.get(kind, {})
        was_enabled = old.get("email_enabled") is True
        is_enabled = toggles.get(kind, was_enabled)
        cutoff = _datetime(old.get("send_not_before"))
        if is_enabled and (not was_enabled or cutoff is None):
            cutoff = now
        types[kind] = {
            "email_enabled": is_enabled,
            "send_not_before": cutoff.isoformat() if cutoff else None,
        }
        if kind not in REQUIRED_KINDS or is_enabled:
            continue
        if was_enabled:
            if not reason:
                raise RequiredKindReasonMissing(kind)
            types[kind].update(paused_reason=reason, paused_at=now.isoformat())
        elif previous.paused_reason(kind):
            types[kind].update(
                paused_reason=previous.paused_reason(kind),
                paused_at=old.get("paused_at"),
            )
    return {
        "enabled": enabled,
        "send_not_before": global_cutoff.isoformat() if global_cutoff else None,
        "types": types,
    }


def policy_changes(before: DeliveryPolicy, after: DeliveryPolicy) -> dict[str, Any]:
    """Co zmienił zapis: wyłącznik globalny i rodzaje maili (``from`` → ``to``)."""
    changes: dict[str, Any] = {}
    if before.enabled != after.enabled:
        changes["enabled"] = {"from": before.enabled, "to": after.enabled}
    types = {}
    for kind in sorted(ROUTINE_KINDS):
        was = before.types.get(kind, {}).get("email_enabled") is True
        now_on = after.types.get(kind, {}).get("email_enabled") is True
        if was != now_on:
            types[kind] = {"from": was, "to": now_on}
    if types:
        changes["types"] = types
    return changes


def _changes_summary(changes: dict[str, Any]) -> str:
    labels = {spec["id"]: spec["label"] for spec in CATALOG}
    parts = []
    if "enabled" in changes:
        parts.append(
            "wysyłka globalna "
            + ("włączona" if changes["enabled"]["to"] else "wyłączona")
        )
    types = changes.get("types", {})
    off = [labels[k] for k, c in types.items() if not c["to"]]
    on = [labels[k] for k, c in types.items() if c["to"]]
    if off:
        parts.append("wyłączono: " + ", ".join(off))
    if on:
        parts.append("włączono: " + ", ".join(on))
    return "Maile automatyczne dla całej firmy — " + "; ".join(parts)


def with_required_kinds(value: Any, now: datetime) -> dict | None:
    """Polityka z włączonymi mailami obowiązkowymi albo `None`, gdy nic nie trzeba.

    Rodzaj obowiązkowy, który nie jest włączony i którego admin nie wstrzymał
    z powodem, dostaje `email_enabled` i próg `now` — wychodzą tylko zdarzenia
    od tej chwili, jak przy ręcznym włączeniu. Wyłącznik globalny zostaje
    decyzją admina: wiersz bez polityki albo z wyłączoną wysyłką — bez zmian.
    """
    policy = DeliveryPolicy.from_value(value)
    if not policy.enabled:
        return None
    missing = [
        kind
        for kind in sorted(REQUIRED_KINDS)
        if not policy.kind_enabled(kind) and not policy.paused_reason(kind)
    ]
    if not missing:
        return None
    return updated_value(
        policy, enabled=True, toggles=dict.fromkeys(missing, True), now=now
    )


async def ensure_required_kinds(db: AsyncSession) -> list[str]:
    """Włącza maile obowiązkowe przy starcie aplikacji; zwraca włączone rodzaje."""
    row = await db.scalar(
        select(AppSetting)
        .where(AppSetting.key == SETTING_KEY)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    value = with_required_kinds(row.value if row else None, datetime.now(timezone.utc))
    if row is None or value is None:
        await db.rollback()
        return []
    before = DeliveryPolicy.from_value(row.value)
    row.value = value
    await db.commit()
    return sorted(
        kind
        for kind in REQUIRED_KINDS
        if DeliveryPolicy.from_value(value).kind_enabled(kind)
        and not before.kind_enabled(kind)
    )


async def save_policy(
    db: AsyncSession,
    *,
    enabled: bool,
    toggles: dict[str, bool],
    admin_id: int,
    actor: Any = None,
    reason: str | None = None,
) -> None:
    await db.execute(
        insert(AppSetting)
        .values(key=SETTING_KEY, value={"enabled": False})
        .on_conflict_do_nothing(index_elements=[AppSetting.key])
    )
    row = await db.scalar(
        select(AppSetting)
        .where(AppSetting.key == SETTING_KEY)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert row is not None
    before = DeliveryPolicy.from_value(row.value)
    row.value = updated_value(
        before,
        enabled=enabled,
        toggles=toggles,
        now=datetime.now(timezone.utc),
        reason=reason,
    )
    row.updated_by = admin_id
    # Przełącznik działa na całą firmę, a do 09.10.2026 nie zostawiał śladu
    # poza `updated_by` — nie było widać, kto wyłączył poranny skrót wszystkim.
    changes = policy_changes(before, DeliveryPolicy.from_value(row.value))
    if actor is not None and changes:
        from app.services.critical_events import record_executed

        summary = _changes_summary(changes)
        paused = [
            kind
            for kind, change in changes.get("types", {}).items()
            if kind in REQUIRED_KINDS and not change["to"]
        ]
        if paused:
            changes["paused_reason"] = (reason or "").strip()[:PAUSE_REASON_MAX]
            summary += f". Powód wstrzymania: {changes['paused_reason']}"
        await record_executed(
            db,
            actor=actor,
            event_type="notifications.email_policy",
            entity_type="settings",
            entity_id=None,
            entity_label="Maile automatyczne",
            reason=summary,
            details=changes,
        )
    await db.commit()


def _iso_epoch(value: Any) -> str | None:
    return (
        datetime.fromtimestamp(value, timezone.utc).isoformat()
        if isinstance(value, (float, int)) and value > 0
        else None
    )


async def _daily_digest_recipient_count(db: AsyncSession) -> int | None:
    """Zasięg porannego skrótu; awaria liczenia nie może zabrać ekranu."""
    try:
        from app.tasks.daily_digest_email import recipient_count

        async with db.begin_nested():
            return await recipient_count(db)
    except Exception:  # noqa: BLE001 — liczba jest informacją, nie warunkiem
        logger.warning("daily digest recipient count failed", exc_info=True)
        return None


async def _self_disabled_names(db: AsyncSession) -> dict[str, list[str]]:
    """Kto wyłączył sobie który mail; awaria liczenia nie może zabrać ekranu."""
    try:
        from app.services.notification_email_prefs import opt_out_summary

        async with db.begin_nested():
            return await opt_out_summary(db)
    except Exception:  # noqa: BLE001 — lista jest informacją, nie warunkiem
        logger.warning("email opt-out summary failed", exc_info=True)
        return {}


async def admin_view(db: AsyncSession) -> dict[str, Any]:
    from app.services.m365 import app_mail, mail_circuit
    from app.services.m365.system_mail import get_system_sender_connection
    from app.tasks.app_mail_monitor import snapshot_queue

    policy = await load_policy(db)
    row = await db.get(AppSetting, SETTING_KEY)
    now = datetime.now(timezone.utc)
    if settings.M365_APP_MAIL_ENABLED:
        try:
            state = await asyncio.to_thread(mail_circuit.snapshot)
            state_available = True
        except Exception:
            logger.warning("notification email provider history unavailable")
            state = {}
            state_available = False
        configured = app_mail.is_configured()
        observed = app_mail.app_mail_send_verdict(
            app_mail.AppMailSendState(
                **{
                    key: state[key]
                    for key in app_mail.AppMailSendState.__dataclass_fields__
                    if key in state
                }
            ),
            configured=configured,
        )
        if configured and not state_available:
            observed = "unknown"
        provider = dict(
            kind="graph_app",
            sender=settings.M365_MAIL_SENDER_UPN or None,
            configured=configured,
            observed_status=observed,
            last_success_at=_iso_epoch(state.get("last_success_at")),
            last_failure_at=_iso_epoch(state.get("last_failure_at")),
            failure_code=state.get("last_failure_code")
            if state_available
            else "monitoring_state_unavailable",
            cooldown_until=_iso_epoch(state.get("next_attempt_at")),
        )
    else:
        configured = bool(settings.SMTP_ENABLED and settings.SMTP_HOST)
        provider = dict(
            kind="smtp" if settings.SMTP_ENABLED else "none",
            sender=settings.SMTP_FROM_EMAIL or None,
            configured=configured,
            observed_status="unknown" if configured else "unconfigured",
            last_success_at=None,
            last_failure_at=None,
            failure_code=None,
            cooldown_until=None,
        )
    delegated = await get_system_sender_connection(db)
    self_disabled = await _self_disabled_names(db)
    types = []
    for spec in CATALOG:
        kind = spec["id"]
        if kind == hr_program.MAIL_KIND and not hr_program.program_enabled():
            continue
        use_delegated = (
            kind in {"job_deadline", "delivery_alert"} and delegated is not None
        )
        cutoff = policy.cutoff_for(kind)
        types.append(
            dict(
                **spec,
                email_enabled=policy.types.get(kind, {}).get("email_enabled") is True,
                effective_enabled=policy.kind_enabled(kind),
                required=kind in REQUIRED_KINDS,
                paused_reason=policy.paused_reason(kind),
                # Kto wyłączył ten mail sobie („Maile do Ciebie”) — żeby admin
                # widział, że firmowe „włączone” nie znaczy „dostają wszyscy”.
                self_disabled=self_disabled.get(kind, []),
                send_not_before=cutoff.isoformat() if cutoff else None,
                channels=["email"]
                if kind in REPORT_KINDS or kind == "application_confirmation"
                else [
                    "client_panel" if kind == "delivery_alert" else "in_app",
                    "email",
                ],
                sender=delegated.mailbox_upn if use_delegated else provider["sender"],
                provider_kind="graph_delegated" if use_delegated else provider["kind"],
                provider_status="unknown"
                if use_delegated
                else provider["observed_status"],
                editable=True,
            )
        )
    for spec in SECURITY_CATALOG:
        types.append(
            dict(
                **spec,
                module="Bezpieczeństwo konta",
                recipient_rule="Właściciel konta, którego dotyczy żądanie.",
                email_enabled=True,
                effective_enabled=True,
                required=True,
                paused_reason=None,
                self_disabled=[],
                send_not_before=None,
                channels=["email"],
                sender=provider["sender"],
                provider_kind=provider["kind"],
                provider_status=provider["observed_status"],
                editable=False,
            )
        )
    queue = await snapshot_queue(db, policy, now)
    updated_by_name = None
    if row is not None and row.updated_by is not None:
        from app.models.user import User

        updated_by_name = await db.scalar(
            select(User.name).where(User.id == row.updated_by)
        )
    return dict(
        enabled=policy.enabled,
        updated_at=row.updated_at.isoformat() if row else None,
        updated_by=row.updated_by if row else None,
        updated_by_name=updated_by_name,
        # Ile kont dostaje poranny skrót — ekran pokazuje zasięg przełącznika.
        daily_digest_recipients=await _daily_digest_recipient_count(db),
        send_not_before=policy.send_not_before.isoformat()
        if policy.send_not_before
        else None,
        provider=provider,
        backlog={
            "pending_retry": queue["pending_retry"],
            "ready_upper_bound": queue["ready_candidates_upper_bound"],
            "uncertain": queue["uncertain"],
            "legacy_suppressed": queue["legacy_suppressed"],
            "scope": queue.get("scope", "routine_email"),
        },
        types=types,
        excluded_channels=[
            dict(
                id="manual_m365",
                label="Korespondencja z osobistej skrzynki",
                description="Ręczne maile, shortlisty i zaplanowane odpowiedzi odmowne korzystają z połączenia Microsoft 365 użytkownika oraz własnych zgód i reguł.",
            ),
            dict(
                id="order_mail_read",
                label="Odczyt poczty i zamówień",
                description="Synchronizacja Microsoft 365 i odczyt zamówień nie są wysyłką powiadomień i nie podlegają temu przełącznikowi.",
            ),
            dict(
                id="account_security",
                label="Bezpieczeństwo konta",
                description="Reset i zmiana hasła oraz weryfikacja adresu działają niezależnie od automatycznych powiadomień.",
            ),
            dict(
                id="external_monitoring",
                label="Monitoring Sentry i Grafana",
                description="Alarmy błędów i infrastruktury mają osobną konfigurację. Te przełączniki sterują automatycznymi mailami NEXUS.",
            ),
        ],
    )
