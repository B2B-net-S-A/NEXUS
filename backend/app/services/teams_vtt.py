"""Transkrypt Teams (WebVTT) → wypowiedzi, tekst i role mówców (0369).

Czyste funkcje, bez bazy i sieci. Teams oddaje transkrypt jako VTT z tagiem
mówcy ``<v Imię Nazwisko>`` przy każdej wypowiedzi. Konto z naszego tenanta
jest podpisane nazwą z katalogu, gość (kandydat) — nazwą, którą sam wpisał,
czasem z dopiskiem „(Gość)”/„(Guest)”.

Rola mówcy:
- ``staff`` — nazwa pasuje do osoby z zespołu (organizator, dopisani uczestnicy);
- ``candidate`` — nazwa zawiera imię i nazwisko kandydata albo jest JEDYNYM
  mówcą spoza zespołu (kandydat wszedł jako „JK laptop”);
- ``unknown`` — reszta. Czas mowy bez podpisu i nieznanych mówców nie wchodzi
  do udziału kandydata, a gdy kandydata nie da się wskazać, udział jest
  ``None`` („nie policzono”), nigdy 0.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional

_TIME = r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?"
_CUE_TIMING = re.compile(rf"^\s*{_TIME}\s*-->\s*{_TIME}")
_VOICE = re.compile(r"<v(?:\.[^\s>]*)?\s+([^>]*)>(.*?)(?:</v>|$)", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_GUEST_SUFFIX = re.compile(
    r"\((?:gość|gosc|guest|zewnętrzny|external|unverified|niezweryfikowany)\)",
    re.IGNORECASE,
)
_PL_FOLD = str.maketrans({"ł": "l", "Ł": "L"})


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    speaker: Optional[str]
    text: str

    @property
    def seconds(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class SpeakerSummary:
    speakers: list[dict]
    candidate_seconds: int
    staff_seconds: int
    unknown_seconds: int
    talk_share: Optional[float]


def _seconds(h: Optional[str], m: str, s: str, ms: Optional[str]) -> float:
    frac = (ms or "0").ljust(3, "0")[:3]
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(frac) / 1000


def parse_vtt(raw: str) -> list[Cue]:
    """Wypowiedzi z pliku VTT. Nieczytelny plik = pusta lista (nie wyjątek)."""
    if not raw:
        return []
    text = raw.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        timing_idx = next(
            (i for i, ln in enumerate(lines) if _CUE_TIMING.match(ln)), None
        )
        if timing_idx is None:
            continue
        m = _CUE_TIMING.match(lines[timing_idx])
        assert m is not None
        start = _seconds(*m.group(1, 2, 3, 4))
        end = _seconds(*m.group(5, 6, 7, 8))
        body = " ".join(lines[timing_idx + 1 :]).strip()
        if not body:
            continue
        speaker: Optional[str] = None
        voice = _VOICE.search(body)
        if voice:
            speaker = voice.group(1).strip() or None
            body = voice.group(2)
        content = re.sub(r"\s+", " ", _TAG.sub("", body)).strip()
        if content:
            cues.append(Cue(start=start, end=end, speaker=speaker, text=content))
    return cues


def render_plain_text(cues: Iterable[Cue]) -> str:
    """„Mówca: tekst” — kolejne wypowiedzi tej samej osoby w jednej linii."""
    lines: list[str] = []
    last_speaker: Optional[str] = object()  # type: ignore[assignment]
    for cue in cues:
        if lines and cue.speaker == last_speaker:
            lines[-1] = f"{lines[-1]} {cue.text}"
            continue
        lines.append(f"{cue.speaker}: {cue.text}" if cue.speaker else cue.text)
        last_speaker = cue.speaker
    return "\n".join(lines)


def normalize_person_name(name: Optional[str]) -> tuple[str, ...]:
    """Posortowane tokeny nazwy: małe litery, bez polskich znaków i dopisków."""
    if not name:
        return ()
    cleaned = _GUEST_SUFFIX.sub(" ", name).translate(_PL_FOLD)
    folded = unicodedata.normalize("NFKD", cleaned)
    ascii_only = "".join(ch for ch in folded if not unicodedata.combining(ch))
    tokens = re.findall(r"[a-z]+", ascii_only.lower())
    return tuple(sorted(t for t in tokens if len(t) > 1))


def _contains(speaker: tuple[str, ...], person: tuple[str, ...]) -> bool:
    return bool(person) and set(person) <= set(speaker)


def classify_speakers(
    cues: list[Cue],
    *,
    staff: list[tuple[Optional[int], str]],
    candidate_name: Optional[str],
) -> SpeakerSummary:
    """Czas mowy per mówca z rolą i udział kandydata w rozmowie."""
    totals: dict[Optional[str], float] = {}
    order: list[Optional[str]] = []
    for cue in cues:
        if cue.speaker not in totals:
            order.append(cue.speaker)
            totals[cue.speaker] = 0.0
        totals[cue.speaker] += cue.seconds

    staff_norm = [(uid, normalize_person_name(n)) for uid, n in staff if n]
    cand_norm = normalize_person_name(candidate_name)

    rows: list[dict] = []
    for name in order:
        if name is None:
            continue
        norm = normalize_person_name(name)
        uid = next((u for u, sn in staff_norm if _contains(norm, sn)), None)
        is_staff = any(_contains(norm, sn) for _, sn in staff_norm)
        role = (
            "staff"
            if is_staff
            else ("candidate" if _contains(norm, cand_norm) else "unknown")
        )
        rows.append(
            {
                "name": name,
                "role": role,
                "user_id": uid if is_staff else None,
                "seconds": round(totals[name]),
            }
        )

    if not any(r["role"] == "candidate" for r in rows):
        others = [r for r in rows if r["role"] == "unknown"]
        if len(others) == 1:
            others[0]["role"] = "candidate"

    def _sum(role: str) -> float:
        return sum(totals[r["name"]] for r in rows if r["role"] == role)

    cand = _sum("candidate")
    stf = _sum("staff")
    unknown = _sum("unknown") + totals.get(None, 0.0)
    share = round(cand / (cand + stf), 3) if cand > 0 and cand + stf > 0 else None
    return SpeakerSummary(
        speakers=rows,
        candidate_seconds=round(cand),
        staff_seconds=round(stf),
        unknown_seconds=round(unknown),
        talk_share=share,
    )
