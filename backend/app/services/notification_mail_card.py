"""Mail z jednego powiadomienia: co zrobić, fakty sprawy i przyciski (26.10.2026).

Decyzja Artura z 26.10.2026 (PR 2 planu maili obowiązkowych,
`docs/claude/powiadomienia/maile-z-przyciskami-akcji.md`): mail z kolejki „od razu”
ma się czytać jak zadanie, nie jak kopia dzwonka:

- temat „[NEXUS] co zrobić · czego dotyczy”, żeby lista w Outlooku była listą
  zadań;
- znaczek „Czeka na Ciebie” albo rodzaj sprawy;
- 2–4 fakty z tej samej sprawy (rekrutacja, klient, Delivery Lead, termin);
- przyciski, które otwierają dokładny ekran z wybraną decyzją do
  potwierdzenia (`/calendar?cycle=…&do=pick&choose=1`,
  `/people/approvals?leave=…&decide=approve`). Ekran nigdy nie wykonuje akcji
  sam — Safe Links w M365 otwiera linki z maila przed człowiekiem, a mail
  przekazany dalej dawałby decyzję komuś innemu. Bez odpowiedzi mailem i bez
  kart Adaptive Cards (decyzja „same przyciski”);
- stopka „przychodzi zawsze” dla rodzajów z `REQUIRED_KINDS`.

`build_card` jest czysta (testy bez bazy); `load_facts` czyta z bazy tylko to,
co wskazują link i encja powiadomienia. Mail „Czas i ludzie” dostaje tytuł
i treść po `hr_mail.mail_text` (bez rodzaju nieobecności i kwot) i fakty tylko
o terminie wniosku — rodzaj i kwoty nie idą nigdy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.services.notification_delivery import HR_MAIL_KIND
from app.services.stage_handoff_recipients import (
    RETURNED_TITLE_PREFIXES,
    TITLE_CPRO_QUEUE,
    TITLE_DL_NUDGE,
    TITLE_DL_REVIEW,
)

WAITING = "Czeka na Ciebie"
OPEN_LABEL = "Otwórz w NEXUSIE"
SETTINGS_PATH = "/settings?item=my-notifications"
FACTS_MAX = 4
SUBJECT_PART_MAX = 70
_WEEKDAYS_PL = ("pon", "wt", "śr", "czw", "pt", "sob", "nd")


@dataclass(frozen=True)
class MailButton:
    label: str
    path: str
    # „primary” = wypełniony; „neg” = szary (odmowa, „nie”).
    style: str = "secondary"


@dataclass(frozen=True)
class MailCard:
    action: str
    about: Optional[str]
    chip: str
    waiting: bool
    title: str
    text: str
    facts: tuple[tuple[str, str], ...]
    buttons: tuple[MailButton, ...]
    required: bool

    @property
    def subject(self) -> str:
        action = _short(self.action, SUBJECT_PART_MAX)
        return f"[NEXUS] {action} · {self.about}" if self.about else f"[NEXUS] {action}"


@dataclass(frozen=True)
class MailFacts:
    """Fakty sprawy odczytane z bazy; każde pole może być puste."""

    candidate: Optional[str] = None
    job: Optional[str] = None
    client: Optional[str] = None
    delivery_lead: Optional[str] = None
    deadline: Optional[date] = None
    start_date: Optional[date] = None
    # Terminy od klienta (początki slotów) i długość rozmowy w minutach.
    slots: tuple[datetime, ...] = ()
    duration_minutes: Optional[int] = None
    chosen_index: Optional[int] = None
    # Wniosek o nieobecność: kto i kiedy — bez rodzaju (D6).
    person: Optional[str] = None
    period: Optional[tuple[date, date]] = None


@dataclass(frozen=True)
class _Spec:
    action: str
    chip: str = WAITING
    label: str = OPEN_LABEL
    # Krok „Rozmów u klienta”, który ma otworzyć przycisk (`?do=`).
    cycle_step: Optional[str] = None
    # Drugi przycisk „Otwórz …” z samym linkiem dzwonka.
    secondary: Optional[str] = None
    # Temat z tytułu dzwonka, gdy tytuł niesie liczbę albo formę zależną od
    # umowy (paczka „Nowe rekrutacje u Twoich klientów: 3”, tytuł premii).
    use_title: bool = False


# Typy powiadomień z kolejki „od razu” → co zrobić i przycisk.
SPECS: dict[str, _Spec] = {
    # Rozmowy u klienta — przycisk otwiera okno kroku w „Rozmowach u klienta”.
    "interview_slots_requested": _Spec(
        "Ustal termin z kandydatem",
        label="Wybierz termin z kandydatem",
        cycle_step="pick",
    ),
    "interview_slot_chosen": _Spec(
        "Potwierdź termin u klienta", label="Potwierdź termin", cycle_step="confirm"
    ),
    "interview_slot_confirmed": _Spec(
        "Zaplanuj prep",
        chip="Rozmowa potwierdzona",
        label="Zaplanuj prep",
        cycle_step="plan_prep",
        secondary="Otwórz rozmowę",
    ),
    "interview_changed": _Spec(
        "Sprawdź zmianę rozmowy", chip="Rozmowa u klienta", label="Otwórz rozmowę"
    ),
    "interview_debrief_saved": _Spec(
        "Przeczytaj debrief", chip="Debrief", label="Otwórz rozmowę"
    ),
    # Link niesie `?debrief=<wydarzenie>` — ekran otwiera okno debriefu.
    "post_interview_t15": _Spec(
        "Zadzwoń do kandydata po rozmowie", label="Zapisz debrief"
    ),
    "prep_candidate_declined": _Spec("Ustal prep na nowo", label="Otwórz prep"),
    "prep_changed_yours": _Spec(
        "Sprawdź zmianę prepu", chip="Prep", label="Otwórz prep"
    ),
    # Rekrutacja: link dzwonka już otwiera kandydata (`?candidate=`) albo
    # przegląd DL (`&review=1`). `board_task_waiting` rozróżnia `BOARD_SPECS`.
    "board_task_waiting": _Spec("Sprawdź zadanie", label="Otwórz"),
    "client_accepted": _Spec(
        "Klient zaakceptował",
        chip="Akceptacja klienta",
        label="Otwórz kandydata w rekrutacji",
    ),
    "pre_contract": _Spec(
        "Umowa przedwstępna", chip="Umowa przedwstępna", label="Otwórz kandydata"
    ),
    "cpro_send_assigned": _Spec("Wyślij CV do klienta", label="Otwórz kandydata"),
    "note_reply": _Spec(
        "Odpowiedź na Twoją notatkę", chip="Notatka", label="Otwórz notatkę"
    ),
    "candidate_claim_taken": _Spec(
        "Ktoś przejął Twoją osobę", chip="Zespół", label="Otwórz kandydata"
    ),
    "job_p0_set": _Spec(
        "Rekrutacja na P0 — ultrapilne", chip="P0", label="Otwórz rekrutację"
    ),
    "job_closed_people_waiting": _Spec(
        "Daj znać swoim osobom",
        chip="Rekrutacja zamknięta",
        label="Otwórz Tablicę",
        use_title=True,
    ),
    "request_assignment_changed": _Spec(
        "Nowa rekrutacja dla Ciebie", chip="Nowa rekrutacja", label="Otwórz rekrutację"
    ),
    "b2b_signature_requested": _Spec(
        "Potwierdź podpis umowy B2B", label="Otwórz umowę"
    ),
    # Link z `?contract=` otwiera panel kontraktora z „Uzupełnij zamówienie”.
    "hired_order_missing": _Spec("Dodaj zamówienie", label="Dodaj zamówienie"),
    "hire_missing_contract": _Spec("Dodaj umowę", label="Otwórz kandydata"),
    "automation_failing": _Spec("Sprawdź automat", chip="Awaria", label="Otwórz"),
    "teams_prep_scope_missing": _Spec("Sprawdź automat", chip="Awaria", label="Otwórz"),
    "candidate_data_access_alert": _Spec(
        "Sprawdź alarm", chip="Bezpieczeństwo", label="Sprawdź konta"
    ),
    # 0609: nowa osoba po pierwszym logowaniu — przyciski otwierają okno
    # „Ustaw” na pulpicie (`?nowa-osoba=`), decyzja zapada dopiero w oknie.
    "new_person_signed_in": _Spec("Zdecyduj, kim jest nowa osoba", label="Zdecyduj"),
    # Czas i ludzie — temat bez rodzaju nieobecności.
    "hr_leave_requested": _Spec("Zatwierdź nieobecność", label="Zatwierdź"),
    "hr_absence_reported": _Spec(
        "Zgłoszona nieobecność", chip="Czas i ludzie", label="Otwórz akceptacje"
    ),
    "hr_timesheet_submitted": _Spec("Zatwierdź raport godzin", label="Otwórz raport"),
    "hr_timesheet_reminder": _Spec("Wyślij raport godzin", label="Otwórz mój miesiąc"),
    # Nowe maile z PR 3 planu (26.10.2026); typy dochodzą tamtym PR-em.
    "client_job_opened": _Spec(
        "Nowa rekrutacja u Twojego klienta", label="Otwórz", use_title=True
    ),
    # Brakujące ogłoszenia (27.10.2026) — kartę składa `job_ad.reminders`;
    # wpis tu to zapasowy opis, gdy tamta karta by nie powstała.
    "job_ad_missing": _Spec("Wstaw ogłoszenia", label="Otwórz ogłoszenie"),
    "job_ad_backlog": _Spec(
        "Nadrób ogłoszenia", chip="Zaległe", label="Nadrabiaj po kolei"
    ),
    "job_ad_nudge": _Spec(
        "Opublikuj na stronie kariery",
        chip="Prośba od DL-a",
        label="Opublikuj na stronie kariery",
    ),
    "hr_bonus_assigned": _Spec(
        "Masz nową premię", chip="Premia", label="Zobacz premię", use_title=True
    ),
}

CV_RETURNED = _Spec("Popraw CV", label="Popraw CV")
# `board_task_waiting` niesie kilka zadań — rozróżnia je początek tytułu
# (stałe `stage_handoff_recipients.TITLE_*`, jak `immediate_email_kind`).
BOARD_SPECS: tuple[tuple[str, _Spec], ...] = (
    (TITLE_DL_REVIEW, _Spec("Przejrzyj CV", label="Przejrzyj CV")),
    (TITLE_CPRO_QUEUE, _Spec("Wrzuć do Cpro", label="Otwórz kandydata")),
    (TITLE_DL_NUDGE, _Spec("Wyślij CV do klienta", label="Otwórz kandydata")),
    *((prefix, CV_RETURNED) for prefix in RETURNED_TITLE_PREFIXES),
)
HR_DEFAULT_CHIP = "Czas i ludzie"
# Tytuł wniosku, o którym odbiorca decyduje (`leave_recipients.notify_requested`);
# „… do wiadomości” dostaje zastępca, który nie decyduje.
LEAVE_DECIDE_TITLE = "Wniosek o nieobecność do akceptacji"


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def with_params(path: str, **params: Optional[str]) -> str:
    """Ścieżka z dołożonymi parametrami (``None`` zdejmuje parametr)."""
    parts = urlsplit(path)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, value in params.items():
        if value is None:
            query.pop(key, None)
        else:
            query[key] = value
    return urlunsplit(("", "", parts.path, urlencode(query), parts.fragment))


def _local(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(ZoneInfo(settings.BUSINESS_TZ))


def slot_label(moment: datetime) -> str:
    """„czw 29.10, 9:30” w strefie firmy."""
    local = _local(moment)
    return f"{_WEEKDAYS_PL[local.weekday()]} {local:%d.%m}, {local.hour}:{local:%M}"


def _day(value: date) -> str:
    return f"{value:%d.%m.%Y}"


def _period(start: date, end: date) -> str:
    if start == end:
        return _day(start)
    if start.year == end.year:
        return f"{start:%d.%m}–{_day(end)}"
    return f"{_day(start)}–{_day(end)}"


def _facts(ntype: str, hr: bool, facts: MailFacts) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, Optional[str]]]
    if hr:
        # Czas i ludzie: tylko kto i kiedy — rodzaju i kwot mail nie niesie.
        rows = [
            ("Kto", facts.person),
            ("Kiedy", _period(*facts.period) if facts.period else None),
        ]
    elif ntype == "interview_slots_requested":
        rows = [
            ("Rekrutacja", facts.job),
            ("Klient", facts.client),
            (
                "Długość",
                f"{facts.duration_minutes} min" if facts.duration_minutes else None,
            ),
            ("Delivery Lead", facts.delivery_lead),
        ]
    elif ntype in {"interview_slot_chosen", "interview_slot_confirmed"}:
        chosen = (
            facts.slots[facts.chosen_index]
            if facts.chosen_index is not None
            and 0 <= facts.chosen_index < len(facts.slots)
            else None
        )
        rows = [
            ("Termin", slot_label(chosen) if chosen else None),
            ("Rekrutacja", facts.job),
            ("Klient", facts.client),
            ("Delivery Lead", facts.delivery_lead),
        ]
    elif ntype == "request_assignment_changed":
        rows = [
            ("Rekrutacja", facts.job),
            ("Klient", facts.client),
            ("Delivery Lead", facts.delivery_lead),
            ("Termin", _day(facts.deadline) if facts.deadline else None),
        ]
    elif ntype in {"hired_order_missing", "hire_missing_contract"}:
        rows = [
            ("Kontraktor", facts.candidate),
            ("Klient", facts.client),
            ("Start", _day(facts.start_date) if facts.start_date else None),
            ("Rekrutacja", facts.job),
        ]
    else:
        rows = [
            ("Kandydat", facts.candidate),
            ("Rekrutacja", facts.job),
            ("Klient", facts.client),
            ("Delivery Lead", facts.delivery_lead),
        ]
    return tuple((k, v) for k, v in rows if v)[:FACTS_MAX]


def _about(ntype: str, hr: bool, facts: MailFacts) -> Optional[str]:
    if hr:
        parts = [facts.person]
    elif ntype in {"request_assignment_changed", "job_closed_people_waiting"}:
        parts = [facts.job, facts.client]
    else:
        parts = [facts.candidate, facts.client]
    # Każda część skracana osobno — długi tytuł rekrutacji nie zjada klienta.
    joined = " · ".join(_short(p, SUBJECT_PART_MAX) for p in parts if p)
    return joined or None


def _buttons(
    ntype: str,
    title: str,
    spec: _Spec,
    link: str,
    facts: MailFacts,
    entity_ref: Optional[str],
) -> tuple[MailButton, ...]:
    if spec.cycle_step and "cycle=" in link:
        step = with_params(link, do=spec.cycle_step)
        if spec.cycle_step == "pick" and len(facts.slots) > 1:
            # Jeden przycisk na termin: okno wyboru z zaznaczonym terminem
            # (`choose` liczone od 1) — nadal z potwierdzeniem w oknie. `req`
            # = wniosek z tymi terminami; przy nowszym wniosku pary front nie
            # zaznacza niczego (przegląd kodu 26.10.2026).
            return tuple(
                MailButton(
                    f"Kandydat wybrał {n} · {slot_label(start)}",
                    with_params(step, choose=str(n), req=entity_ref),
                    "primary",
                )
                for n, start in enumerate(facts.slots, start=1)
            ) + (MailButton("Otwórz rozmowę", link),)
        buttons = [MailButton(spec.label, step, "primary")]
        if spec.secondary:
            buttons.append(MailButton(spec.secondary, link))
        return tuple(buttons)
    if ntype == "hired_order_missing" and entity_ref and "/clients/" in link:
        return (
            MailButton(spec.label, with_params(link, contract=entity_ref), "primary"),
        )
    decides = ntype == "hr_leave_requested" and title.startswith(LEAVE_DECIDE_TITLE)
    if decides and "leave=" in link:
        return (
            MailButton("Zatwierdź", with_params(link, decide="approve"), "primary"),
            MailButton("Odrzuć", with_params(link, decide="reject"), "neg"),
            MailButton("Otwórz wniosek", with_params(link, decide=None)),
        )
    if ntype == "new_person_signed_in" and "nowa-osoba=" in link:
        return (
            MailButton(spec.label, link, "primary"),
            MailButton("Zostaw jako Konsultanta", with_params(link, zostaw="1"), "neg"),
        )
    if ntype == "hr_leave_requested":
        # Wniosek „do wiadomości” (zastępca przy L4) albo bez numeru w linku.
        return (MailButton("Otwórz akceptacje", link, "primary"),)
    return (MailButton(spec.label, link, "primary"),)


def _spec(notification_type: str, kind: Optional[str], title: str) -> Optional[_Spec]:
    if notification_type == "board_task_waiting":
        for prefix, spec in BOARD_SPECS:
            if title.startswith(prefix):
                return spec
    if kind == "cv_returned":
        return CV_RETURNED
    return SPECS.get(notification_type)


def build_card(
    *,
    notification_type: str,
    kind: Optional[str],
    title: str,
    message: str,
    link: Optional[str],
    required: bool,
    facts: MailFacts = MailFacts(),
    entity_ref: Optional[str] = None,
) -> MailCard:
    """Karta maila z powiadomienia. Bez bazy — fakty podaje wołający."""
    link = link or "/dashboard"
    hr = kind == HR_MAIL_KIND
    spec = _spec(notification_type, kind, title)
    if spec is None:
        # Typ bez opisu (czat, sprawy kadrowe bez decyzji): tytuł dzwonka
        # jako „co zrobić” i jeden przycisk do ekranu.
        spec = _Spec(title, chip=HR_DEFAULT_CHIP if hr else "NEXUS")
    return MailCard(
        action=title if spec.use_title else spec.action,
        about=_about(notification_type, hr, facts),
        chip=spec.chip,
        waiting=spec.chip == WAITING,
        title=title,
        text=message,
        facts=_facts(notification_type, hr, facts),
        buttons=_buttons(notification_type, title, spec, link, facts, entity_ref),
        required=required,
    )


# ── Odczyt faktów z bazy ──────────────────────────────────────────────────────

_JOB_RE = re.compile(r"^/jobs/(\d+)")
_CLIENT_RE = re.compile(r"^/clients/(\d+)")
_CYCLE_RE = re.compile(r"^(\d+)-(\d+)$")


def link_refs(link: Optional[str]) -> dict[str, int]:
    """Identyfikatory z linku dzwonka: job, candidate, client."""
    if not link:
        return {}
    parts = urlsplit(link)
    query = dict(parse_qsl(parts.query))
    refs: dict[str, int] = {}
    if m := _JOB_RE.match(parts.path):
        refs["job"] = int(m.group(1))
    if m := _CLIENT_RE.match(parts.path):
        refs["client"] = int(m.group(1))
    if (raw := query.get("candidate")) and raw.isdigit():
        refs["candidate"] = int(raw)
    if (raw := query.get("cycle")) and (m := _CYCLE_RE.match(raw)):
        refs["candidate"], refs["job"] = int(m.group(1)), int(m.group(2))
    return refs


def _person_name(candidate: Any) -> Optional[str]:
    if candidate is None:
        return None
    name = " ".join(
        p
        for p in (
            getattr(candidate, "name", None),
            getattr(candidate, "lastname", None),
        )
        if p
    )
    return name or None


def _parse_slot(raw: Any) -> Optional[datetime]:
    start = raw.get("start") if isinstance(raw, dict) else None
    try:
        return datetime.fromisoformat(start) if isinstance(start, str) else None
    except ValueError:
        return None


async def load_facts(db: Any, notif: Any) -> MailFacts:
    """Fakty sprawy z bazy. Brak wiersza = puste pole, nigdy wyjątek dla maila."""
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_interview_slot_request import ClientInterviewSlotRequest
    from app.models.contract import Contract
    from app.models.job import Job
    from app.models.user import User

    refs = link_refs(notif.link)
    values: dict[str, Any] = {}
    entity = notif.related_entity_type
    entity_id = notif.related_entity_id
    if entity == "interview_slot_request" and entity_id:
        req = await db.get(ClientInterviewSlotRequest, entity_id)
        if req is not None:
            refs.setdefault("candidate", req.candidate_id)
            refs.setdefault("job", req.job_id)
            values["slots"] = tuple(
                s for s in (_parse_slot(raw) for raw in req.slots or []) if s
            )
            values["duration_minutes"] = req.duration_minutes
            values["chosen_index"] = req.chosen_index
    if entity == "contract" and entity_id:
        contract = await db.get(Contract, entity_id)
        if contract is not None:
            if contract.candidate_id:
                refs.setdefault("candidate", contract.candidate_id)
            if contract.job_id:
                refs.setdefault("job", contract.job_id)
            refs.setdefault("client", contract.client_id)
            values["start_date"] = contract.start_date

    job = await db.get(Job, refs["job"]) if "job" in refs else None
    if job is not None:
        values["job"] = getattr(job, "working_title", None) or job.title
        values["deadline"] = job.deadline
        refs.setdefault("client", job.client_id)
        if job.delivery_lead_id:
            lead = await db.get(User, job.delivery_lead_id)
            values["delivery_lead"] = getattr(lead, "name", None)
    if "candidate" in refs:
        values["candidate"] = _person_name(await db.get(Candidate, refs["candidate"]))
    if "client" in refs:
        client = await db.get(Client, refs["client"])
        if client is not None:
            # Krótka nazwa jak w dzwonku; `display_name` to pełna nazwa prawna.
            values["client"] = client.name or client.display_name
    if entity == "leave_request":
        values.update(await _leave_facts(db, notif.link))
    return MailFacts(**values)


async def _leave_facts(db: Any, link: Optional[str]) -> dict[str, Any]:
    import uuid

    from app.models.hr_leave import LeaveRequest
    from app.models.user import User

    raw = dict(parse_qsl(urlsplit(link or "").query)).get("leave")
    try:
        leave_id = uuid.UUID(raw) if raw else None
    except ValueError:
        leave_id = None
    request = await db.get(LeaveRequest, leave_id) if leave_id else None
    if request is None:
        return {}
    person = await db.get(User, request.user_id)
    return {
        "person": getattr(person, "name", None),
        "period": (request.start_date, request.end_date),
    }
