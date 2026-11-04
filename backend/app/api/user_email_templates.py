"""User email templates library — Phase 4.5 of the M365 plan.

CRUD + render for per-user M365 outreach templates. Rendered with a
Jinja2 SandboxedEnvironment so user-supplied template source can't reach
Python internals (no access to ``__class__``/``__subclasses__`` etc.).

Endpoints (mounted under /api/user-email-templates):
- GET    /                  — list own + shared
- POST   /                  — create (auto-detects variables from body)
- GET    /{id}              — single (own OR shared)
- PUT    /{id}              — update (owner-only)
- DELETE /{id}              — delete (owner-only)
- POST   /{id}/render       — render Jinja2 with candidate/job context

The render endpoint resolves the optional candidate_id / request_id / job_id
to ORM rows and exposes them to the template under the namespaces
`candidate`, `request`, `job`, `user`, `today`.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import os
import re
import resource
import string
import sys
import time
from collections.abc import ItemsView, KeysView, Mapping, ValuesView
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from jinja2 import TemplateError, meta, select_autoescape
from jinja2.compiler import CodeGenerator, optimizeconst
from jinja2.exceptions import SecurityError
from jinja2.sandbox import SandboxedEnvironment
from jinja2.utils import Namespace, _PassArg
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analytics.capabilities import AnalyticsCapability, user_has_capability
from app.api.candidate_access import CandidatePIIAccess, CandidateWriteAccess
from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.user import UserRole
from app.models.user_email_template import UserEmailTemplate
from app.services.access_scope import (
    assert_delivery_lead_client_visible,
    resolve_delivery_lead_org_client_ids,
)
from app.core.scheduling import business_today

router = APIRouter()


# Runda 9 (R9-N10-7): render szablonu autora szedł synchronicznie w handlerze
# async — `{% for a in range(100000) %}{% for b in range(100000) %}` albo
# `9 ** 9 ** 9` zamrażały jedyny proces uvicorna. Teraz: działania `*`/`**`
# i liczby w wywołaniach mają sufit, render ma limit czasu (twardy — sprawdzany
# w trakcie wykonania) i limit długości wyniku, a całość idzie w wątku.
_MAX_CALL_INT = 10_000_000
_MAX_SEQ_REPEAT = 100_000
_MAX_INT_BITS = 4_096
_RENDER_OUTPUT_LIMIT = 500_000
_RENDER_DEADLINE_SECONDS = 2.0
# Runda 10 (R10-V3-1): sufity z rundy 9 obejmowały wyłącznie `*`/`**` i samo
# wyjście. `s + s` (albo `~`, `"%99999999s" % x`, `"{:99999999}".format(x)`,
# `|replace(old=, new=)`, `|join`, `|indent`) budowały w JEDNYM wywołaniu kodu
# C napis wielu GB, zanim funkcja śledząca albo limit wyniku zdążyły
# zareagować — OOM zabijał jedyny proces uvicorna. Teraz każdy napis pośredni
# ma ten sam sufit co wynik, liczony PRZED operacją; bufor bloków
# (`{% set x %}…{% endset %}`, makra) liczy, co do niego trafia; zamiana
# kolekcji na tekst (wyjście, `~`, `%s`, filtry tekstowe) liczy jej długość
# tekstową bez budowania jej; a pętla w Pythonie, która alokuje za dużo,
# przerywa się przy przyroście pamięci procesu.
_MAX_LIST_ITEMS = 100_000
_RENDER_MEMORY_GROWTH_LIMIT = 512 * 1024 * 1024
_TRACER_CHECK_EVERY = 256
_MAX_SPEC_DIGITS = 9
_SPEC_NUMBER_RE = re.compile(r"\d+")
_PERCENT_SPEC_CHARS = frozenset("-#0 +*.123456789")
_FORMATTER = string.Formatter()
# Metody napisów bez zastosowania w mailu, które mnożą długość tekstu
# (`translate` z długimi wartościami) albo wyprowadzają poza `str` (`encode`).
_BLOCKED_STR_METHODS = frozenset({"translate", "maketrans", "encode"})
# Filtry, które zamieniają wartość na tekst — kolekcja z wieloma odwołaniami do
# tego samego długiego napisu daje w nich tekst wielu GB jednym `str()`.
_STRINGIFY_FILTERS = frozenset(
    {
        "capitalize",
        "e",
        "escape",
        "forceescape",
        "lower",
        "pprint",
        "safe",
        "string",
        "striptags",
        "title",
        "tojson",
        "trim",
        "truncate",
        "upper",
        "urlencode",
        "urlize",
        "wordcount",
        "xmlattr",
    }
)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_call_args(args: tuple, kwargs: dict) -> None:
    for value in (*args, *kwargs.values()):
        if _is_int(value) and abs(value) > _MAX_CALL_INT:
            raise SecurityError("Liczba w szablonie przekracza dopuszczalny limit.")


def _ensure_size(size: int) -> None:
    if size > _RENDER_OUTPUT_LIMIT:
        raise SecurityError("Wynik szablonu przekracza dopuszczalny limit.")


def _text_weight(value: Any, budget: int = _RENDER_OUTPUT_LIMIT) -> int:
    """Górne oszacowanie długości tekstu z `str(value)`, liczone bez budowania go.

    Zatrzymuje się po przekroczeniu budżetu — każdy element dokłada co najmniej
    dwa znaki, więc liczenie kosztuje najwyżej ~budżet kroków, także dla listy
    ze stoma tysiącami odwołań do tego samego napisu albo listy, która zawiera
    samą siebie.
    """
    total = 0
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, (str, bytes, bytearray)):
            total += len(item) + 2
        elif isinstance(item, (list, tuple, set, frozenset, KeysView, ValuesView)):
            total += 2 + 2 * len(item)
            if total > budget:
                return total
            stack.extend(item)
        elif isinstance(item, (Mapping, ItemsView)):
            pairs = item.items() if isinstance(item, Mapping) else item
            total += 2 + 4 * len(pairs)
            if total > budget:
                return total
            for key, val in pairs:
                stack.append(key)
                stack.append(val)
        elif isinstance(item, Namespace):
            total += 12
            stack.append(item._Namespace__attrs)
        elif _is_int(item):
            total += item.bit_length() // 3 + 2
        else:
            total += 32
        if total > budget:
            return total
    return total


def _ensure_text_weight(value: Any) -> None:
    _ensure_size(_text_weight(value))


def _spec_numbers(spec: str) -> int:
    """Suma liczb w specyfikacji formatu (szerokość, precyzja) — górny sufit
    dopełnienia, które doda formatowanie."""
    total = 0
    for run in _SPEC_NUMBER_RE.findall(spec):
        if len(run) > _MAX_SPEC_DIGITS:
            raise SecurityError("Szerokość pola w szablonie przekracza limit.")
        total += int(run)
    return total


def _percent_format_size(fmt: str, values: Any) -> int:
    """Oszacowanie długości `fmt % values` przed wykonaniem (liniowe)."""
    size = len(fmt) + _text_weight(values)
    length = len(fmt)
    i = fmt.find("%")
    while i != -1 and i + 1 < length:
        j = i + 1
        if fmt[j] == "(":
            # Klucz mapowania liczony jak w Pythonie (z zagnieżdżonymi
            # nawiasami) — inaczej `%((x))999s` chowałby szerokość za kluczem.
            depth = 1
            j += 1
            while j < length and depth:
                if fmt[j] == "(":
                    depth += 1
                elif fmt[j] == ")":
                    depth -= 1
                j += 1
            if depth:
                break
        begin = j
        while j < length and fmt[j] in _PERCENT_SPEC_CHARS:
            j += 1
        spec = fmt[begin:j]
        if "*" in spec:
            raise SecurityError("Szerokość pola z argumentu nie jest dostępna.")
        size += _spec_numbers(spec)
        if size > _RENDER_OUTPUT_LIMIT:
            return size
        i = fmt.find("%", j + 1)
    return size


def _new_format_size(fmt: str, args: Any, kwargs: Any) -> int:
    """Oszacowanie długości `fmt.format(...)` przed wykonaniem."""
    size = len(fmt) + _text_weight(args) + _text_weight(kwargs)
    try:
        fields = list(_FORMATTER.parse(fmt))
    except ValueError:
        return size  # Python odrzuci ten format sam
    for _literal, _field, spec, _conversion in fields:
        if not spec:
            continue
        if "{" in spec:
            raise SecurityError("Zagnieżdżone pola formatu nie są dostępne.")
        size += _spec_numbers(spec)
        if size > _RENDER_OUTPUT_LIMIT:
            return size
    return size


def _check_replace(subject: Any, old: Any, new: Any) -> None:
    """Sufit wyniku `replace` liczony PRZED wywołaniem (przegląd rundy 9):
    jedno wywołanie w kodzie C buduje napis 10¹⁰ znaków, zanim funkcja
    śledząca albo limit długości wyniku zdążą zareagować."""
    if not (isinstance(subject, str) and isinstance(new, str)):
        return
    hits = (
        len(subject) + 1
        if not old
        else subject.count(old)
        if isinstance(old, str)
        else 0
    )
    _ensure_size(len(subject) + hits * len(new))


def _join_size(separator: Any, items: list) -> int:
    sep = len(separator) if isinstance(separator, str) else _text_weight(separator)
    return sep * max(len(items) - 1, 0) + _text_weight(items)


def _width(value: Any) -> int:
    return value if _is_int(value) else 0


def _check_filter(name: str, value: Any, arguments: dict) -> Any:
    """Sufit wyniku filtra liczony przed wywołaniem. Zwraca wartość do użycia
    (iterator zamieniony na listę, żeby liczenie go nie zużyło)."""
    if name == "replace":
        _check_replace(value, arguments.get("old"), arguments.get("new"))
    elif name == "join":
        if not isinstance(value, (str, list)):
            value = list(value)
        _ensure_size(_join_size(arguments.get("d", ""), value))
    elif name == "format":
        values = arguments.get("kwargs") or arguments.get("args") or ()
        _ensure_size(_percent_format_size(str(value), values))
    elif name == "indent":
        text = value if isinstance(value, str) else str(value)
        width = arguments.get("width", 4)
        per_line = width if _is_int(width) else _text_weight(width)
        _ensure_size(len(text) + (text.count("\n") + 1) * max(per_line, 0))
    elif name == "center":
        _ensure_size(max(_text_weight(value), _width(arguments.get("width", 80))))
    elif name == "wordwrap":
        text = value if isinstance(value, str) else str(value)
        width = max(_width(arguments.get("width", 79)), 1)
        wrap = arguments.get("wrapstring") or "\n"
        breaks = len(text) // width + text.count(" ") + text.count("\n") + 1
        _ensure_size(len(text) + breaks * _text_weight(wrap))
    elif name == "sum":
        start = arguments.get("start", 0)
        if not isinstance(start, (int, float)):
            # `sum(start=[])` skleja listy w czasie kwadratowym w kodzie C.
            raise SecurityError("Filtr sum przyjmuje wyłącznie liczby.")
    elif name in _STRINGIFY_FILTERS:
        _ensure_text_weight(value)
    return value


def _check_str_method(owner: str, name: str, args: tuple, kwargs: dict) -> tuple:
    """Sufit wyniku metody napisu liczony przed wywołaniem."""
    if name == "replace":
        old = args[0] if args else kwargs.get("old")
        new = args[1] if len(args) > 1 else kwargs.get("new")
        _check_replace(owner, old, new)
    elif name == "join" and args:
        items = list(args[0])
        _ensure_size(_join_size(owner, items))
        return (items, *args[1:])
    elif name in {"center", "ljust", "rjust", "zfill"}:
        width = args[0] if args else kwargs.get("width")
        _ensure_size(max(len(owner), _width(width)))
    elif name == "expandtabs":
        tabsize = args[0] if args else kwargs.get("tabsize", 8)
        _ensure_size(len(owner) + owner.count("\t") * max(_width(tabsize), 0))
    return args


def _check_list_growth(owner: list, name: str, args: tuple) -> tuple:
    if name == "extend" and args:
        items = list(args[0])
        if len(owner) + len(items) > _MAX_LIST_ITEMS:
            raise SecurityError("Lista w szablonie przekracza limit.")
        return (items, *args[1:])
    if len(owner) + 1 > _MAX_LIST_ITEMS:
        raise SecurityError("Lista w szablonie przekracza limit.")
    return args


def _bounded_filter(name: str, func):
    """Filtr z sufitem liczb w argumentach (np. `|center(10**9)`) i sufitem
    długości wyniku liczonym przed wywołaniem (Runda 10: także argumenty
    nazwane, np. `|replace(old="", new=s)`)."""
    skip = 2 if _PassArg.from_obj(func) is not None else 1
    # Podpis funkcji właściwej bez parametrów kontekstu (warianty async Jinja
    # dokładają `eval_ctx`, którego funkcja synchroniczna nie deklaruje).
    target = inspect.unwrap(func)
    params = list(inspect.signature(target).parameters.values())
    context_params = 1 if _PassArg.from_obj(target) is not None else 0
    signature = inspect.Signature(params[context_params:])

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        _check_call_args(args[skip:], kwargs)
        if len(args) < skip:
            return func(*args, **kwargs)
        try:
            bound = signature.bind(*args[skip - 1 :], **kwargs)
        except TypeError:
            return func(*args, **kwargs)  # zły wywołujący — niech odmówi Jinja
        bound.apply_defaults()
        value = args[skip - 1]
        checked = _check_filter(name, value, dict(bound.arguments))
        if checked is not value:
            args = (*args[: skip - 1], checked, *args[skip:])
        return func(*args, **kwargs)

    return wrapper


class _BoundedBuffer(list):
    """Bufor bloku (`{% set x %}`, makro, `{% filter %}`) z sufitem długości —
    bez niego `concat` bufora budował jednym wywołaniem napis wielu GB."""

    __slots__ = ("_size",)

    def __init__(self) -> None:
        super().__init__()
        self._size = 0

    def _grow(self, items) -> None:
        for item in items:
            self._size += len(item) if isinstance(item, str) else _text_weight(item)
        _ensure_size(self._size)

    def append(self, item) -> None:
        self._grow((item,))
        super().append(item)

    def extend(self, items) -> None:
        items = tuple(items)
        self._grow(items)
        super().extend(items)


class _BoundedCodeGenerator(CodeGenerator):
    def buffer(self, frame) -> None:
        frame.buffer = self.temporary_identifier()
        self.writeline(f"{frame.buffer} = environment.bounded_buffer()")

    @optimizeconst
    def visit_Concat(self, node, frame) -> None:
        # Jak `CodeGenerator.visit_Concat`, tylko części idą najpierw przez
        # `environment.bounded_concat_parts` — sufit przed złożeniem napisu.
        if frame.eval_ctx.volatile:
            func_name = "(markup_join if context.eval_ctx.volatile else str_join)"
        elif frame.eval_ctx.autoescape:
            func_name = "markup_join"
        else:
            func_name = "str_join"
        self.write(f"{func_name}(environment.bounded_concat_parts((")
        for arg in node.nodes:
            self.visit(arg, frame)
            self.write(", ")
        self.write(")))")


class _BoundedSandbox(SandboxedEnvironment):
    intercepted_binops = frozenset({"*", "**", "+", "%"})
    code_generator_class = _BoundedCodeGenerator

    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        self.filters = {
            name: _bounded_filter(name, func) for name, func in self.filters.items()
        }
        # `lipsum(n)` generuje dowolnie długi tekst — w mailu niepotrzebny.
        self.globals.pop("lipsum", None)

    @staticmethod
    def bounded_buffer() -> _BoundedBuffer:
        return _BoundedBuffer()

    @staticmethod
    def bounded_concat_parts(parts: tuple) -> tuple:
        _ensure_size(
            sum(len(p) if isinstance(p, str) else _text_weight(p) for p in parts)
        )
        return parts

    def wrap_str_format(self, value: Any):
        # `str.format`/`format_map` Jinja owija przy odczycie atrybutu, więc
        # wywołanie nie przechodzi przez `call` — sufit stoi tutaj.
        wrapped = super().wrap_str_format(value)
        if wrapped is None:
            return None
        owner = value.__self__
        is_format_map = value.__name__ == "format_map"

        @functools.wraps(wrapped)
        def bounded(*args: Any, **kwargs: Any) -> str:
            if is_format_map:
                mapping = args[0] if args else {}
                _ensure_size(_new_format_size(owner, (), mapping))
            else:
                _ensure_size(_new_format_size(owner, args, kwargs))
            return wrapped(*args, **kwargs)

        return bounded

    def is_safe_attribute(self, obj: Any, attr: str, value: Any) -> bool:
        if isinstance(obj, str) and attr in _BLOCKED_STR_METHODS:
            return False
        return super().is_safe_attribute(obj, attr, value)

    def call(__self, __context, __obj, *args, **kwargs):  # noqa: N805
        _check_call_args(args, kwargs)
        owner = getattr(__obj, "__self__", None)
        name = getattr(__obj, "__name__", "")
        if isinstance(owner, str):
            args = _check_str_method(owner, name, args, kwargs)
        elif isinstance(owner, list) and name in {"append", "extend", "insert"}:
            args = _check_list_growth(owner, name, args)
        return super().call(__context, __obj, *args, **kwargs)

    def call_binop(self, context, operator, left, right):
        if operator == "**" and _is_int(left) and _is_int(right):
            if (
                right > 0
                and abs(left) > 1
                and (right * abs(left).bit_length() > _MAX_INT_BITS)
            ):
                raise SecurityError("Potęga w szablonie przekracza limit.")
        if operator == "*":
            sequences = (str, bytes, bytearray, list, tuple)
            for seq, times in ((left, right), (right, left)):
                if isinstance(seq, sequences) and _is_int(times):
                    if len(seq) * max(times, 0) > _MAX_SEQ_REPEAT:
                        raise SecurityError(
                            "Powielenie tekstu w szablonie przekracza limit."
                        )
            if (
                _is_int(left)
                and _is_int(right)
                and (left.bit_length() + right.bit_length() > _MAX_INT_BITS)
            ):
                raise SecurityError("Iloczyn w szablonie przekracza limit.")
        if operator == "+":
            texts = (str, bytes, bytearray)
            if isinstance(left, texts) and isinstance(right, texts):
                _ensure_size(len(left) + len(right))
            elif isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
                if len(left) + len(right) > _MAX_LIST_ITEMS:
                    raise SecurityError("Lista w szablonie przekracza limit.")
        if operator == "%" and isinstance(left, str):
            _ensure_size(_percent_format_size(left, right))
        return super().call_binop(context, operator, left, right)


def _finalize(value: Any) -> Any:
    # Jinja renderuje `None` jako napis "None". `_candidate_ctx` i `_job_ctx`
    # celowo zwracają `None` dla pól nieuzupełnionych (`full_name`,
    # `client_name`, `phone`, `location`, `linkedin`, widełki), więc szablon
    # z `{{ candidate.phone }}` wysyłał KANDYDATOWI maila z napisem "None".
    # Ten sam defekt co w `contract_templates`, tylko z odbiorcą na zewnątrz.
    # `finalize` zamienia wyłącznie `None` na pusty napis: `False` i `0` muszą
    # przejść nietknięte, bo są prawidłowymi wartościami, a nie brakiem danych.
    if value is None:
        return ""
    if not isinstance(value, str):
        # Runda 10 (R10-V3-1): `{{ [s] * 100000 }}` — `str()` listy odwołań
        # do długiego napisu to jedno wywołanie w C budujące wiele GB.
        _ensure_text_weight(value)
    return value


# Sandboxed so user-supplied template source can't reach Python internals.
# autoescape=True since rendered output is injected as HTML into Tiptap.
_jinja_env = _BoundedSandbox(
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
    finalize=_finalize,
)

# Runda 9 (R9-N10-6): temat to zwykły tekst (nagłówek maila), nie HTML —
# środowisko z autoescape zamieniało „R&D” w „R&amp;D” w skrzynce kandydata.
_subject_env = _BoundedSandbox(
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
    finalize=_finalize,
)


class _RenderTimeout(SecurityError):
    pass


_PAGE_SIZE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096


def _process_memory() -> int | None:
    """Bieżąca pamięć procesu (RSS) w bajtach; `None`, gdy system jej nie podaje.

    Linux (produkcja, CI): `/proc/self/statm`. Poza nim — szczyt z `getrusage`
    (przyrost szczytu też oznacza, że render alokuje za dużo).
    """
    try:
        with open("/proc/self/statm", "rb") as handle:
            return int(handle.read().split()[1]) * _PAGE_SIZE
    except (OSError, ValueError, IndexError):
        pass
    try:
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (OSError, ValueError):
        return None
    return peak if sys.platform == "darwin" else peak * 1024


def _render_bounded(env: SandboxedEnvironment, source: str, ctx: dict) -> str:
    """Render z twardym limitem czasu i długości wyniku (wołany w wątku).

    Limit czasu sprawdza funkcja śledząca wątku — przerywa także pętlę, która
    nic nie wypisuje (samo `asyncio.wait_for` nie zatrzymałoby wątku).
    """
    template = env.from_string(source)
    deadline = time.monotonic() + _RENDER_DEADLINE_SECONDS
    memory_start = _process_memory()
    ticks = 0

    def _tracer(frame, event, arg):
        nonlocal ticks
        ticks += 1
        if ticks % _TRACER_CHECK_EVERY == 0:
            if time.monotonic() > deadline:
                raise _RenderTimeout("Render szablonu przekroczył limit czasu.")
            # Runda 10 (R10-V3-1): pętla w Pythonie (`|map('upper')` na liście
            # długich napisów) alokuje GB w czasie krótszym niż limit czasu.
            if (
                memory_start is not None
                and (_process_memory() or 0) - memory_start
                > _RENDER_MEMORY_GROWTH_LIMIT
            ):
                raise SecurityError("Render szablonu przekroczył limit pamięci.")
        return _tracer

    previous = sys.gettrace()
    sys.settrace(_tracer)
    try:
        parts: list[str] = []
        size = 0
        for chunk in template.generate(**ctx):
            size += len(chunk)
            if size > _RENDER_OUTPUT_LIMIT:
                raise SecurityError("Wynik szablonu przekracza dopuszczalną długość.")
            parts.append(chunk)
        return "".join(parts)
    finally:
        sys.settrace(previous)


async def _render_in_thread(env: SandboxedEnvironment, source: str, ctx: dict) -> str:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_render_bounded, env, source, ctx),
            timeout=_RENDER_DEADLINE_SECONDS * 3,
        )
    except asyncio.TimeoutError as exc:
        raise _RenderTimeout("Render szablonu przekroczył limit czasu.") from exc


def _extract_variables(body_html: str) -> List[str]:
    """Parse Jinja2 source and return the sorted list of referenced vars.

    Returns top-level names (``candidate`` not ``candidate.first_name``) — the
    UI groups by namespace anyway. Empty list if the body has no variables.
    """
    try:
        ast = _jinja_env.parse(body_html)
    except TemplateError:
        # Caller will surface a 422 from validation; for save-time we still
        # want to persist *some* variables list rather than crash here.
        return []
    return sorted(meta.find_undeclared_variables(ast))


def _validate_jinja(template_src: str, field_name: str) -> None:
    """Raise 422 if Jinja2 cannot parse the source."""
    try:
        _jinja_env.parse(template_src)
    except TemplateError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid Jinja2 syntax in {field_name}: {e}",
        )


# ── Pydantic schemas ────────────────────────────────────────────────────────


class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    subject: Optional[str] = Field(None, max_length=998)
    body_html: str = Field(..., min_length=1)
    is_shared: bool = False


class TemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    subject: Optional[str] = Field(None, max_length=998)
    body_html: Optional[str] = Field(None, min_length=1)
    is_shared: Optional[bool] = None


class TemplateResponse(BaseModel):
    id: int
    user_id: int
    name: str
    subject: Optional[str]
    body_html: str
    variables: List[str]
    is_shared: bool
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_row(cls, t: UserEmailTemplate) -> "TemplateResponse":
        return cls(
            id=t.id,
            user_id=t.user_id,
            name=t.name,
            subject=t.subject,
            body_html=t.body_html,
            variables=list(t.variables or []),
            is_shared=t.is_shared,
            created_at=t.created_at.isoformat() if t.created_at else "",
            updated_at=t.updated_at.isoformat() if t.updated_at else "",
        )


class RenderRequest(BaseModel):
    candidate_id: Optional[int] = None
    request_id: Optional[int] = None
    job_id: Optional[int] = None


class RenderResponse(BaseModel):
    rendered_subject: str
    rendered_body_html: str
    unresolved_vars: List[str]


# ── Helpers ─────────────────────────────────────────────────────────────────


def _candidate_ctx(c: Optional[Candidate]) -> dict:
    if c is None:
        return {}
    full = f"{c.name} {c.lastname}".strip() if (c.name or c.lastname) else None
    return {
        "id": c.id,
        "first_name": c.name,
        "last_name": c.lastname,
        "full_name": full,
        "email": c.email,
        "phone": c.phone,
        "location": c.location,
        "linkedin": c.linkedin,
    }


def _job_ctx(j: Optional[Job], *, include_finance: bool = False) -> dict:
    if j is None:
        return {}
    client = getattr(j, "client", None)
    return {
        "id": j.id,
        "title": j.title,
        "role_name": j.title,
        "location": j.location,
        "client_name": client.name if client else None,
        "salary_min": j.salary_min if include_finance else None,
        "salary_max": j.salary_max if include_finance else None,
    }


def _user_ctx(u) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
    }


def _build_render_context(
    template: UserEmailTemplate,
    current_user,
    candidate: Optional[Candidate],
    job: Optional[Job],
    *,
    include_finance: bool = False,
) -> dict:
    """Assemble the dict exposed to Jinja2 templates.

    Keep this shape STABLE — it's effectively the public contract for what
    variables template authors can use. New keys = additive; renames or
    removals will break existing templates in the wild.
    """
    job_ctx = _job_ctx(job, include_finance=include_finance)
    return {
        "candidate": _candidate_ctx(candidate),
        "request": job_ctx,
        "job": job_ctx,
        "user": _user_ctx(current_user),
        "today": business_today().isoformat(),
    }


def _collect_unresolved(template_src: str, ctx: dict) -> List[str]:
    """Return Jinja2 top-level vars that aren't present in the render context."""
    try:
        ast = _jinja_env.parse(template_src)
    except TemplateError:
        return []
    return sorted(v for v in meta.find_undeclared_variables(ast) if v not in ctx)


async def _load_template_for_read(
    template_id: int,
    user_id: int,
    db: AsyncSession,
) -> UserEmailTemplate:
    """Owner OR shared. 404 otherwise."""
    t = await db.scalar(
        select(UserEmailTemplate).where(
            UserEmailTemplate.id == template_id,
            or_(
                UserEmailTemplate.user_id == user_id,
                UserEmailTemplate.is_shared.is_(True),
            ),
        )
    )
    if t is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    return t


async def _load_template_for_write(
    template_id: int,
    user_id: int,
    db: AsyncSession,
) -> UserEmailTemplate:
    """Owner only — separated from read to give 404 vs 403 the right semantics."""
    t = await db.scalar(
        select(UserEmailTemplate).where(UserEmailTemplate.id == template_id)
    )
    if t is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
        )
    if t.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only modify your own templates",
        )
    return t


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("", response_model=List[TemplateResponse])
async def list_templates(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Own templates + every shared template (from any user)."""
    res = await db.execute(
        select(UserEmailTemplate)
        .where(
            or_(
                UserEmailTemplate.user_id == current_user.id,
                UserEmailTemplate.is_shared.is_(True),
            )
        )
        .order_by(UserEmailTemplate.updated_at.desc())
    )
    return [TemplateResponse.from_orm_row(t) for t in res.scalars().all()]


# Runda 9 (R9-N10-11): szablon wspólny widzi każdy — publikuje go tylko autor
# szablonów systemowych (lustro `emails.EmailTemplateAuthor`: admin, HoR, DL).
_SHARED_TEMPLATE_AUTHOR_ROLES = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
)


def _assert_can_share(current_user) -> None:
    if not current_user.has_any_role(*_SHARED_TEMPLATE_AUTHOR_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Szablon wspólny dla całego zespołu może opublikować tylko "
                "administrator, Head of Recruitment albo Delivery Lead."
            ),
        )


@router.post("", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    data: TemplateCreate,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    if data.is_shared:
        _assert_can_share(current_user)
    _validate_jinja(data.body_html, "body_html")
    if data.subject:
        _validate_jinja(data.subject, "subject")

    t = UserEmailTemplate(
        user_id=current_user.id,
        name=data.name,
        subject=data.subject,
        body_html=data.body_html,
        variables=_extract_variables(data.body_html),
        is_shared=data.is_shared,
    )
    db.add(t)
    await db.flush()
    await db.refresh(t)
    await db.commit()
    return TemplateResponse.from_orm_row(t)


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    t = await _load_template_for_read(template_id, current_user.id, db)
    return TemplateResponse.from_orm_row(t)


@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: int,
    data: TemplateUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    t = await _load_template_for_write(template_id, current_user.id, db)

    updates = data.model_dump(exclude_unset=True)
    if updates.get("is_shared") and not t.is_shared:
        _assert_can_share(current_user)
    if "body_html" in updates and updates["body_html"] is not None:
        _validate_jinja(updates["body_html"], "body_html")
        updates["variables"] = _extract_variables(updates["body_html"])
    if "subject" in updates and updates["subject"]:
        _validate_jinja(updates["subject"], "subject")

    for k, v in updates.items():
        setattr(t, k, v)
    await db.flush()
    await db.refresh(t)
    await db.commit()
    return TemplateResponse.from_orm_row(t)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    t = await _load_template_for_write(template_id, current_user.id, db)
    await db.delete(t)
    await db.commit()


@router.post("/{template_id}/render", response_model=RenderResponse)
async def render_template(
    template_id: int,
    payload: RenderRequest,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    """Render the template with the provided candidate/job context.

    Missing entities produce empty namespaces (e.g. no candidate_id →
    `candidate.first_name` resolves to undefined). The response lists
    unresolved top-level vars so the UI can warn the user.

    P0.5: the render context exposes candidate email/phone/location/linkedin.
    Previously this endpoint took a bare ``CurrentUser``, so a read-only viewer
    could author ``{{ candidate.email }}`` and enumerate PII across candidate
    IDs. It now requires ``CandidatePIIAccess`` (the same internal-operational
    roles allowed to read candidate PII elsewhere), which excludes the viewer.
    """
    t = await _load_template_for_read(template_id, current_user.id, db)

    candidate: Optional[Candidate] = None
    if payload.candidate_id is not None:
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == payload.candidate_id)
        )

    # `request_id` is treated as a Job id — Nexus uses the same primary key
    # for "rekrutacja / request" and "job" (one row, dual naming in the
    # product). Frontend may send either field; we pick the first set.
    job_id = payload.job_id if payload.job_id is not None else payload.request_id
    job: Optional[Job] = None
    if job_id is not None:
        job = await db.scalar(
            select(Job).where(Job.id == job_id).options(selectinload(Job.client))
        )
        if job is not None:
            assert_delivery_lead_client_visible(
                job.client_id,
                await resolve_delivery_lead_org_client_ids(current_user, db),
            )

    ctx = _build_render_context(
        t,
        current_user,
        candidate,
        job,
        include_finance=user_has_capability(
            current_user, AnalyticsCapability.VIEW_FINANCE
        ),
    )

    try:
        rendered_body = await _render_in_thread(_jinja_env, t.body_html, ctx)
    except TemplateError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Render error in body: {e}",
        )

    rendered_subject = ""
    if t.subject:
        try:
            rendered_subject = await _render_in_thread(_subject_env, t.subject, ctx)
        except TemplateError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Render error in subject: {e}",
            )

    unresolved = _collect_unresolved(t.body_html, ctx)
    if t.subject:
        unresolved = sorted(set(unresolved) | set(_collect_unresolved(t.subject, ctx)))

    return RenderResponse(
        rendered_subject=rendered_subject,
        rendered_body_html=rendered_body,
        unresolved_vars=unresolved,
    )
