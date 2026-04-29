"""KPI Coach — polskie szablony wiadomości (toast + bell).

Każdy `(nudge_type, kpi_id)` ma min 3 warianty. Wybór wariantu jest
deterministyczny (hash po user+kpi+bucket+nudge_type) — ten sam user
tego samego dnia dostanie ten sam wariant, ale użytkownicy między sobą
dostają różne copy.

Ton: koleżeński, po polsku, z imieniem usera + emoji. Zgodnie z feedbackiem
Artura ("koleżeński tone, nie formalny").

Placeholdery obsługiwane w każdym template:
  {name}            — pierwsze imię usera (split po spacji, fallback: email)
  {current}         — bieżąca wartość
  {target}          — target
  {remaining}       — max(target - current, 0)
  {progress_pct}    — round(progress_pct)
  {title_pl}        — tytuł KPI z katalogu (np. "Aktywności dziś")

`remind_behind` dodatkowo rozróżnia 3 poziomy eskalacji (0/1/2), wybór
nie jest już losowy — określa go service przez `_select_reminder_variant`
bazując na liczbie remindów już wysłanych tego dnia/tygodnia/miesiąca.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

from app.models.kpi_nudge_log import KpiNudgeType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MessageTemplate:
    title: str
    body: str
    emoji: str


@dataclass(frozen=True)
class RenderedMessage:
    title: str
    body: str
    emoji: str
    variant: int
    # Odzwierciedla kontekst dla frontend toasta (styl).
    tone: str  # "praise" | "remind" | "summary"


# ── Helpers ────────────────────────────────────────────────────────────────


def _first_name(name: str, email: str) -> str:
    """Wyciąga pierwsze imię z `name`. Fallback: local-part emaila."""
    if name and name.strip():
        return name.strip().split()[0]
    return email.split("@", 1)[0] if email else "Koleżanko"


def _tone_for(nudge_type: KpiNudgeType) -> str:
    if nudge_type == KpiNudgeType.praise_hit:
        return "praise"
    if nudge_type == KpiNudgeType.streak_bonus:
        return "praise"
    if nudge_type == KpiNudgeType.eod_summary:
        return "summary"
    return "remind"


def _deterministic_variant(
    *, user_id: int, kpi_id: str, period_bucket: str, nudge_type: KpiNudgeType, n: int
) -> int:
    """Deterministyczny wybór wariantu w [0, n)."""
    if n <= 1:
        return 0
    key = f"{user_id}|{kpi_id}|{period_bucket}|{nudge_type.value}".encode("utf-8")
    digest = hashlib.sha256(key).digest()
    return digest[0] % n


# ── praise_hit ─────────────────────────────────────────────────────────────

_PRAISE_HIT_PER_KPI: dict[str, tuple[MessageTemplate, ...]] = {
    "daily_activity_count": (
        MessageTemplate(
            title="🔥 Daily activity HIT!",
            body="{name}, rozbiłeś dzisiejsze aktywności ({current}/{target}). "
            "Tak trzymaj!",
            emoji="🔥",
        ),
        MessageTemplate(
            title="👏 Brawo, target wyrobiony",
            body="{name}, daily activity na {current} — minąłeś target. "
            "Kawa zasłużona ☕",
            emoji="👏",
        ),
        MessageTemplate(
            title="🚀 Jedziesz z koksem",
            body="{name}, {current}/{target} aktywności dziś — HIT! Szacun.",
            emoji="🚀",
        ),
    ),
    "daily_new_candidates": (
        MessageTemplate(
            title="🎯 Kandydaci dobici",
            body="{name}, {current}/{target} nowych kandydatów dzisiaj — robota!",
            emoji="🎯",
        ),
        MessageTemplate(
            title="💪 Pełen baner kandydatów",
            body="{name}, target nowych kandydatów HIT ({current}/{target}). "
            "Tak się pracuje.",
            emoji="💪",
        ),
        MessageTemplate(
            title="🙌 Target daily zamknięty",
            body="{name}, masz już {current} nowych kandydatów — minąłeś próg. "
            "Dobra robota!",
            emoji="🙌",
        ),
    ),
    "weekly_cvs_sent": (
        MessageTemplate(
            title="📨 Tygodniówka CV zamknięta!",
            body="{name}, {current}/{target} CV do klienta w tym tygodniu — HIT! "
            "Ekipa by Cię wyściskała.",
            emoji="📨",
        ),
        MessageTemplate(
            title="🏆 CV target tygodnia",
            body="{name}, wybiłeś tygodniowy target CV ({current}/{target}). "
            "Placement coraz bliżej.",
            emoji="🏆",
        ),
        MessageTemplate(
            title="✅ Tygodniowe CV — done",
            body="{name}, {current} wysłane, target {target} zrealizowany. "
            "Tydzień kończysz z głową.",
            emoji="✅",
        ),
    ),
    "weekly_screenings": (
        MessageTemplate(
            title="🎙️ Screeningi HIT!",
            body="{name}, {current}/{target} screeningów w tygodniu — target zamknięty.",
            emoji="🎙️",
        ),
        MessageTemplate(
            title="🧠 Rozmowy zrobione",
            body="{name}, screeningi wyrobione ({current}/{target}). Trzymaj tempo!",
            emoji="🧠",
        ),
        MessageTemplate(
            title="⚡ Screening target",
            body="{name}, {current} screeningów w tym tygodniu — minąłeś {target}. "
            "Kandydaci idą jak z nut.",
            emoji="⚡",
        ),
    ),
    "monthly_placements": (
        MessageTemplate(
            title="🎉 Placement target miesiąca!",
            body="{name}, {current}/{target} placementów w tym miesiącu — "
            "LEGENDO. Ekipa bije brawo.",
            emoji="🎉",
        ),
        MessageTemplate(
            title="🏆 Miesiąc zamknięty",
            body="{name}, miesięczny target placementów HIT ({current}/{target}). "
            "Naprawdę moc!",
            emoji="🏆",
        ),
        MessageTemplate(
            title="💎 Placementy — target",
            body="{name}, {current} placementów w miesiącu — minąłeś próg. "
            "Tak wygląda A-player.",
            emoji="💎",
        ),
    ),
}

_PRAISE_HIT_GENERIC: tuple[MessageTemplate, ...] = (
    MessageTemplate(
        title="🔥 Target HIT!",
        body='{name}, "{title_pl}" wyrobione ({current}/{target}). Brawo!',
        emoji="🔥",
    ),
    MessageTemplate(
        title="👏 Robota zrobiona",
        body='{name}, target "{title_pl}" zamknięty ({current}/{target}). Szacun!',
        emoji="👏",
    ),
    MessageTemplate(
        title="🚀 Goalllll",
        body='{name}, {current}/{target} — "{title_pl}" HIT. Tak trzymać.',
        emoji="🚀",
    ),
)


# ── remind_behind — 3 poziomy eskalacji × KPI-aware warianty ───────────────

# Index 0 = delikatny, 1 = stanowczy, 2 = ostatni dzwonek.
_REMIND_BEHIND_ESCALATION_GENERIC: tuple[MessageTemplate, ...] = (
    MessageTemplate(
        title="💡 Mały nudge",
        body='{name}, jeszcze {remaining} do targetu "{title_pl}" '
        "({current}/{target}). Dasz radę!",
        emoji="💡",
    ),
    MessageTemplate(
        title="⏰ Target czeka",
        body='{name}, "{title_pl}" wciąż otwarte ({current}/{target}). '
        "Zostało Ci {remaining} do hit'u — dobrze by było dociągnąć dziś.",
        emoji="⏰",
    ),
    MessageTemplate(
        title="🚨 Last call",
        body='{name}, finalne przypomnienie — "{title_pl}" {current}/{target}, '
        "brakuje {remaining}. Jeszcze jest moment!",
        emoji="🚨",
    ),
)

_REMIND_BEHIND_PER_KPI: dict[str, tuple[MessageTemplate, ...]] = {
    "daily_activity_count": (
        MessageTemplate(
            title="💡 Delikatne przypomnienie",
            body="{name}, aktywności dziś {current}/{target}. "
            "Jeszcze {remaining} do hit'u — dasz radę!",
            emoji="💡",
        ),
        MessageTemplate(
            title="⏰ Daily activity czeka",
            body="{name}, wciąż {current}/{target} aktywności dzisiaj. "
            "Zostało {remaining} do targetu — czas ruszyć z koksem.",
            emoji="⏰",
        ),
        MessageTemplate(
            title="🚨 Ostatni dzwonek dnia",
            body="{name}, zostało niewiele czasu — {current}/{target} "
            "aktywności. Brakuje {remaining}, last call!",
            emoji="🚨",
        ),
    ),
    "weekly_cvs_sent": (
        MessageTemplate(
            title="💡 CV target się nie zrobi sam",
            body="{name}, {current}/{target} CV w tym tygodniu. "
            "Jeszcze {remaining} — placement bliżej niż myślisz.",
            emoji="💡",
        ),
        MessageTemplate(
            title="⏰ Tygodniówka CV",
            body="{name}, CV do klienta {current}/{target}. "
            "Brakuje {remaining} — warto dociągnąć przed końcem tygodnia.",
            emoji="⏰",
        ),
        MessageTemplate(
            title="🚨 Piątek i CV nie wyrobione",
            body="{name}, last call — CV {current}/{target}, zostało {remaining}. "
            "Jeszcze jest czas, ale coraz mniej.",
            emoji="🚨",
        ),
    ),
    "daily_new_candidates": (
        MessageTemplate(
            title="💡 Kandydaci do dobicia",
            body="{name}, nowi kandydaci dziś {current}/{target}. Brakuje {remaining}.",
            emoji="💡",
        ),
        MessageTemplate(
            title="⏰ Daily kandydaci",
            body="{name}, {current}/{target} nowych dziś — jeszcze {remaining} "
            "do targetu. Tempo!",
            emoji="⏰",
        ),
        MessageTemplate(
            title="🚨 Ostatni moment dzisiaj",
            body="{name}, brakuje {remaining} kandydatów do targetu ({current}/{target}). "
            "Ostatnia godzina dnia, dasz radę?",
            emoji="🚨",
        ),
    ),
}


# ── eod_summary ────────────────────────────────────────────────────────────

_EOD_SUMMARY_VARIANTS: tuple[MessageTemplate, ...] = (
    MessageTemplate(
        title="📊 Podsumowanie dnia",
        body="{name}, kończymy dzień. {progress_pct}% średniego postępu "
        "na Twoich dziennych KPI. Jutro gramy dalej 💪",
        emoji="📊",
    ),
    MessageTemplate(
        title="🌇 Koniec dnia roboczego",
        body="{name}, dzień się zamyka — Twój średni postęp dzienny: "
        "{progress_pct}%. Dobrej regeneracji!",
        emoji="🌇",
    ),
    MessageTemplate(
        title="📈 Daily wrap-up",
        body="{name}, {progress_pct}% targetów dziennych zaliczone. "
        "Jutro kontynuujemy — do zobaczenia rano!",
        emoji="📈",
    ),
)


# ── streak_bonus (rezerwa na fazę 2, ale szablon wypełniony) ───────────────

_STREAK_BONUS_GENERIC: tuple[MessageTemplate, ...] = (
    MessageTemplate(
        title="🔥 Streak!",
        body="{name}, seria 3+ dni z targetem — bijesz rekordy. Respekt!",
        emoji="🔥",
    ),
)


# ── Public API ─────────────────────────────────────────────────────────────


def render(
    *,
    nudge_type: KpiNudgeType,
    kpi_id: str,
    kpi_title_pl: str,
    user_id: int,
    user_name: str,
    user_email: str,
    current: int,
    target: int,
    progress_pct: float,
    period_bucket: str,
    forced_variant: Optional[int] = None,
) -> RenderedMessage:
    """Zwraca wyrenderowaną wiadomość dla podanego KPI i typu nudge'a.

    `forced_variant` — używany dla `remind_behind`, gdzie service podaje
    indeks eskalacji (0/1/2) zamiast deterministycznego haszowania.
    Dla pozostałych nudge types: pozostaw None → deterministyczny wybór.
    """
    variants = _lookup_variants(nudge_type, kpi_id)
    if forced_variant is not None:
        variant_idx = max(0, min(forced_variant, len(variants) - 1))
    else:
        variant_idx = _deterministic_variant(
            user_id=user_id,
            kpi_id=kpi_id,
            period_bucket=period_bucket,
            nudge_type=nudge_type,
            n=len(variants),
        )
    tpl = variants[variant_idx]

    first_name = _first_name(user_name, user_email)
    remaining = max(target - current, 0)

    def _fmt(s: str) -> str:
        try:
            return s.format(
                name=first_name,
                current=current,
                target=target,
                remaining=remaining,
                progress_pct=round(progress_pct),
                title_pl=kpi_title_pl,
            )
        except (KeyError, IndexError) as e:  # pragma: no cover
            logger.warning("Template format failed (%s): %s", s, e)
            return s

    return RenderedMessage(
        title=_fmt(tpl.title),
        body=_fmt(tpl.body),
        emoji=tpl.emoji,
        variant=variant_idx,
        tone=_tone_for(nudge_type),
    )


def _lookup_variants(
    nudge_type: KpiNudgeType, kpi_id: str
) -> tuple[MessageTemplate, ...]:
    """Per-KPI warianty jeśli zdefiniowane, inaczej generic fallback."""
    if nudge_type == KpiNudgeType.praise_hit:
        return _PRAISE_HIT_PER_KPI.get(kpi_id) or _PRAISE_HIT_GENERIC
    if nudge_type == KpiNudgeType.remind_behind:
        return _REMIND_BEHIND_PER_KPI.get(kpi_id) or _REMIND_BEHIND_ESCALATION_GENERIC
    if nudge_type == KpiNudgeType.eod_summary:
        return _EOD_SUMMARY_VARIANTS
    if nudge_type == KpiNudgeType.streak_bonus:
        return _STREAK_BONUS_GENERIC
    raise ValueError(f"Unknown nudge_type: {nudge_type}")  # pragma: no cover


def select_reminder_variant(existing_count: int) -> int:
    """Eskalacja przypomnień. Index zwraca `render()` jako `forced_variant`.

    0 = delikatny (pierwsze przypomnienie dnia/tygodnia/miesiąca)
    1 = stanowczy (drugie przypomnienie)
    2 = ostatni dzwonek (trzecie i każde kolejne — cap na 2)
    """
    return min(max(existing_count, 0), 2)
