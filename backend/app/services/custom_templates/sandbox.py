"""Render wzoru własnego w izolacji i walidacja szablonu przy zapisie.

Wzór własny to DOCX od człowieka (albo szkic asystenta), więc szablon nie jest
kodem zaufanym jak wzory z repo. Dwie warstwy:

1. **Walidacja przy zapisie** (``validate``) — drzewo Jinja każdej części pliku
   (treść, nagłówki, stopki, przypisy, właściwości dokumentu) przechodzi przez
   białą listę węzłów: wolno wypisać pole z listy, ``if``/``else``, porównania,
   ``and``/``or``/``not``, kilka filtrów tekstowych i pętlę ``for`` WYŁĄCZNIE po
   polu-liście. Nieznana zmienna, wywołanie funkcji, indeks, atrybut zaczynający
   się od ``_`` albo atrybut czegokolwiek poza polem (``''.__class__``) — błąd.
2. **Render** (``render``) — ``jinja2.sandbox.SandboxedEnvironment`` ze
   ``StrictUndefined`` i kontekstem zbudowanym wyłącznie z pól
   (``fields.build_context``); przed renderem walidacja biegnie jeszcze raz,
   więc wzór zapisany starszą wersją reguł nie ominie nowej.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docxtpl import DocxTemplate
from jinja2 import StrictUndefined, TemplateSyntaxError, nodes
from jinja2.sandbox import SandboxedEnvironment

from app.core.docx_metadata import clear_app_properties, clear_author_metadata
from app.services.custom_templates.fields import (
    AllowedPaths,
    CustomField,
    allowed_paths,
    build_context,
)

MAX_DOCX_BYTES = 5 * 1024 * 1024
#: Limity po rozpakowaniu (wzór: ``legal_redline.docx_io.load_package``):
#: 5 MB ZIP-a z zerami rozpakowuje się do gigabajtów (zip bomb).
MAX_UNZIPPED_BYTES = 80 * 1024 * 1024
MAX_PART_BYTES = 40 * 1024 * 1024
MAX_ZIP_ENTRIES = 1000
MAX_SOURCE_CHARS = 3_000_000
#: Łączny wynik renderu wszystkich części (XML Worda). Jedna pętla po liście
#: (najwyżej ``fields.MAX_LIST_ITEMS`` pozycji) w zwykłym wzorze daje ułamek tego.
MAX_RENDER_CHARS = 8_000_000

ALLOWED_FILTERS: frozenset[str] = frozenset(
    {"upper", "lower", "capitalize", "title", "trim", "default", "join", "length"}
)
ALLOWED_TESTS: frozenset[str] = frozenset(
    {"defined", "none", "string", "number", "sameas", "eq", "ne"}
)
LOOP_ATTRS: frozenset[str] = frozenset({"index", "index0", "first", "last", "length"})

_FOOTNOTES_CT = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
)
_CORE_PROPS = ("author", "comments", "identifier", "language", "subject", "title")


class TemplateInvalid(ValueError):
    """Szablon nie przeszedł walidacji — ``problems`` dla człowieka."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class Validation:
    problems: list[str] = field(default_factory=list)
    #: Ścieżki, które szablon faktycznie czyta (do raportu nieużytych pól).
    used: set[str] = field(default_factory=set)
    #: Tryb zbierania (``discover``): pola-listy i klucze ich pozycji.
    lists: dict[str, set[str]] = field(default_factory=dict)

    def unused(self, fields: list[CustomField]) -> list[str]:
        """Pola z listy, których treść nie czyta (pole płci czytają ``g.*``,
        kwotę — także jej zapis słownie)."""
        used = set(self.used)
        if any(u.startswith("g.") for u in used):
            used |= {f.key for f in fields if f.kind == "gender"}
        used |= {u.removesuffix("_words") for u in used}
        return [f.label for f in fields if f.key not in used]


class RenderTooLarge(TemplateInvalid):
    """Wynik renderu przekroczył ``MAX_RENDER_CHARS`` — render przerwany."""

    def __init__(self) -> None:
        super().__init__(
            [
                "Wynik wzoru jest za duży (ponad "
                f"{MAX_RENDER_CHARS // 1_000_000} mln znaków) — skróć listy albo treść wzoru."
            ]
        )


class DocxTooLarge(ValueError):
    """Plik Word nie mieści się w limitach (spakowany albo po rozpakowaniu)."""


def check_package(docx_bytes: bytes) -> None:
    """Rozmiar pliku, liczba części i rozmiar każdej części po rozpakowaniu —
    przed ``DocxTemplate``/``docx.Document``. Rozmiar z nagłówka ZIP-a jest
    wiążący: ``zipfile`` nie odda więcej bajtów, niż deklaruje część."""
    if len(docx_bytes) > MAX_DOCX_BYTES:
        raise DocxTooLarge("Plik Word jest większy niż 5 MB.")
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as archive:
            infos = archive.infolist()
    except (zipfile.BadZipFile, ValueError) as exc:
        raise DocxTooLarge("Nie udało się otworzyć pliku Word (.docx).") from exc
    if len(infos) > MAX_ZIP_ENTRIES:
        raise DocxTooLarge("Plik Word ma za dużo części.")
    if any(info.file_size > MAX_PART_BYTES for info in infos):
        raise DocxTooLarge("Część pliku Word jest za duża po rozpakowaniu.")
    if sum(info.file_size for info in infos) > MAX_UNZIPPED_BYTES:
        raise DocxTooLarge("Plik Word jest za duży po rozpakowaniu.")


class _BoundedTemplate(SandboxedEnvironment.template_class):  # type: ignore[misc,valid-type]
    """Render kawałkami z licznikiem wspólnym dla wszystkich części pliku:
    po przekroczeniu limitu przerywa, zanim wynik zajmie pamięć procesu."""

    def render(self, *args: object, **kwargs: object) -> str:
        budget = getattr(self.environment, "render_budget", None)
        out: list[str] = []
        for chunk in self.generate(*args, **kwargs):
            if budget is not None:
                budget[0] -= len(chunk)
                if budget[0] < 0:
                    raise RenderTooLarge()
            out.append(chunk)
        return "".join(out)


def _env() -> SandboxedEnvironment:
    env = SandboxedEnvironment(
        autoescape=True,
        undefined=StrictUndefined,
        finalize=lambda v: "" if v is None else v,
    )
    # Tylko filtry z białej listy — reszta (``attr``, ``map``, ``format`` …)
    # znika ze środowiska, żeby ominięcie walidacji niczego nie dało.
    env.filters = {k: v for k, v in env.filters.items() if k in ALLOWED_FILTERS}
    env.tests = {k: v for k, v in env.tests.items() if k in ALLOWED_TESTS}
    env.globals = {}
    env.template_class = _BoundedTemplate
    env.render_budget = [MAX_RENDER_CHARS]  # type: ignore[attr-defined]
    return env


def template_sources(docx_bytes: bytes) -> list[tuple[str, str]]:
    """Źródło Jinja każdej części, którą docxtpl renderuje: ``(część, źródło)``."""
    check_package(docx_bytes)
    tpl = DocxTemplate(io.BytesIO(docx_bytes))
    tpl.init_docx()
    out: list[tuple[str, str]] = [("treść", tpl.patch_xml(tpl.get_xml()))]
    for uri, label in ((RT.HEADER, "nagłówek"), (RT.FOOTER, "stopka")):
        for _, part in tpl.get_headers_footers(uri):
            out.append((label, tpl.patch_xml(tpl.get_part_xml(part))))
    for part in tpl.docx.part.package.parts:
        if part.content_type == _FOOTNOTES_CT:
            blob = (
                part.blob.decode("utf-8") if isinstance(part.blob, bytes) else part.blob
            )
            out.append(("przypisy", tpl.patch_xml(blob)))
    props = tpl.docx.core_properties
    for name in _CORE_PROPS:
        value = getattr(props, name) or ""
        if value:
            out.append((f"właściwość {name}", value))
    return out


class _Checker:
    """Spacer po drzewie Jinja. ``collect=True`` (``discover``) nie zgłasza
    nieznanych pól, tylko je zbiera — tak powstaje lista pól z gotowego
    szablonu (wzór bazowy, Word z polami ``{{ }}``)."""

    def __init__(
        self,
        allowed: AllowedPaths,
        result: Validation,
        part: str,
        *,
        collect: bool = False,
    ):
        self.allowed = allowed
        self.result = result
        self.part = part
        self.collect = collect

    def problem(self, node: nodes.Node, text: str) -> None:
        # Numer wiersza w XML-u Worda nic człowiekowi nie mówi — sama część.
        message = f"{text} ({self.part})"
        if message not in self.result.problems:
            self.result.problems.append(message)

    def unknown(self, node: nodes.Node, path: str) -> None:
        if self.collect:
            self.result.used.add(path)
        else:
            self.problem(node, f"Nieznane pole „{path}”")

    # ── wyrażenia ────────────────────────────────────────────────────────
    def path(self, node: nodes.Getattr) -> tuple[nodes.Node, list[str]]:
        attrs: list[str] = []
        current: nodes.Node = node
        while isinstance(current, nodes.Getattr):
            attrs.insert(0, current.attr)
            current = current.node
        return current, attrs

    def expr(self, node: nodes.Node, scope: dict[str, str]) -> None:
        if isinstance(node, nodes.Const):
            if not isinstance(node.value, (str, int, float, bool, type(None))):
                self.problem(node, "Niedozwolona stała")
            return
        if isinstance(node, nodes.Name):
            name = node.name
            if name in scope:
                if self.allowed.lists.get(scope[name]):
                    self.problem(
                        node, f"Pozycja listy „{name}” wymaga klucza ({name}.…)"
                    )
                return
            if name in self.allowed.scalars or name in self.allowed.lists:
                self.result.used.add(name)
                return
            self.unknown(node, name)
            return
        if isinstance(node, nodes.Getattr):
            base, attrs = self.path(node)
            if any(a.startswith("_") for a in attrs):
                self.problem(node, "Niedozwolony dostęp do atrybutu „_…”")
                return
            if not isinstance(base, nodes.Name):
                self.problem(node, "Atrybut dozwolony tylko na polu wzoru")
                return
            if base.name == "loop" and "loop" in scope:
                if len(attrs) != 1 or attrs[0] not in LOOP_ATTRS:
                    self.problem(node, f"Niedozwolone „loop.{'.'.join(attrs)}”")
                return
            if base.name in scope:
                if self.collect and len(attrs) == 1:
                    self.result.lists.setdefault(scope[base.name], set()).add(attrs[0])
                    return
                items = self.allowed.lists.get(scope[base.name], frozenset())
                if len(attrs) != 1 or attrs[0] not in items:
                    self.problem(
                        node,
                        f"Nieznany klucz pozycji „{base.name}.{'.'.join(attrs)}”",
                    )
                return
            full = ".".join([base.name, *attrs])
            if full in self.allowed.scalars or full in self.allowed.lists:
                self.result.used.add(full)
                return
            self.unknown(node, full)
            return
        if isinstance(node, nodes.Filter):
            if node.name not in ALLOWED_FILTERS:
                self.problem(node, f"Niedozwolony filtr „{node.name}”")
                return
            if node.node is None:
                self.problem(node, "Blok filtra niedozwolony")
                return
            self.expr(node.node, scope)
            self.args(node, scope)
            return
        if isinstance(node, nodes.Test):
            if node.name not in ALLOWED_TESTS:
                self.problem(node, f"Niedozwolony test „{node.name}”")
                return
            self.expr(node.node, scope)
            self.args(node, scope)
            return
        if isinstance(node, (nodes.And, nodes.Or)):
            self.expr(node.left, scope)
            self.expr(node.right, scope)
            return
        if isinstance(node, nodes.Not):
            self.expr(node.node, scope)
            return
        if isinstance(node, nodes.Compare):
            self.expr(node.expr, scope)
            for op in node.ops:
                self.expr(op.expr, scope)
            return
        if isinstance(node, nodes.CondExpr):
            self.expr(node.test, scope)
            self.expr(node.expr1, scope)
            if node.expr2 is not None:
                self.expr(node.expr2, scope)
            return
        if isinstance(node, nodes.Concat):
            for child in node.nodes:
                self.expr(child, scope)
            return
        if isinstance(node, (nodes.List, nodes.Tuple)):
            for child in node.items:
                if not isinstance(child, nodes.Const):
                    self.problem(child, "W liście wolno tylko stałe")
            return
        if isinstance(node, nodes.Call):
            self.problem(node, "Wywołania funkcji są niedozwolone")
            return
        if isinstance(node, (nodes.Getitem, nodes.Slice)):
            self.problem(node, "Indeksowanie jest niedozwolone")
            return
        self.problem(node, f"Niedozwolone wyrażenie ({type(node).__name__})")

    def args(self, node: nodes.Filter | nodes.Test, scope: dict[str, str]) -> None:
        if node.kwargs or node.dyn_args or node.dyn_kwargs:
            self.problem(node, "Argumenty nazwane są niedozwolone")
        for arg in node.args:
            if not isinstance(arg, nodes.Const):
                self.problem(arg, "Argument filtra musi być stałą")

    # ── instrukcje ───────────────────────────────────────────────────────
    def stmts(self, body: list[nodes.Node], scope: dict[str, str]) -> None:
        for node in body:
            self.stmt(node, scope)

    def stmt(self, node: nodes.Node, scope: dict[str, str]) -> None:
        if isinstance(node, nodes.Output):
            for child in node.nodes:
                if isinstance(child, nodes.TemplateData):
                    continue
                self.expr(child, scope)
            return
        if isinstance(node, nodes.If):
            self.expr(node.test, scope)
            self.stmts(node.body, scope)
            for branch in node.elif_:
                self.stmt(branch, scope)
            self.stmts(node.else_, scope)
            return
        if isinstance(node, nodes.For):
            if "loop" in scope:
                # Pętla w pętli mnoży wynik (30 pozycji do potęgi głębokości):
                # cztery poziomy to setki tysięcy akapitów z jednego wzoru.
                self.problem(
                    node,
                    "Pętla w pętli jest niedozwolona — wzór może mieć tylko jeden poziom „for”",
                )
                return
            if node.recursive or node.test is not None:
                self.problem(node, "Pętla rekurencyjna albo z warunkiem niedozwolona")
            if not isinstance(node.target, nodes.Name):
                self.problem(node, "Pętla po jednej zmiennej („for x in lista”)")
                return
            if self.collect and isinstance(node.iter, nodes.Name):
                self.result.lists.setdefault(node.iter.name, set())
            elif not isinstance(node.iter, nodes.Name) or (
                node.iter.name not in self.allowed.lists
            ):
                self.problem(node, "Pętla wolno tylko po polu-liście wzoru")
                return
            else:
                self.result.used.add(node.iter.name)
            inner = {**scope, node.target.name: node.iter.name, "loop": ""}
            self.stmts(node.body, inner)
            self.stmts(node.else_, scope)
            return
        self.problem(node, f"Niedozwolona instrukcja ({type(node).__name__})")


def validate_sources(
    sources: list[tuple[str, str]], fields: list[CustomField]
) -> Validation:
    allowed = allowed_paths(fields)
    result = Validation()
    env = _env()
    if sum(len(s) for _, s in sources) > MAX_SOURCE_CHARS:
        result.problems.append("Plik jest za duży na wzór.")
        return result
    for part, source in sources:
        try:
            tree = env.parse(source)
        except TemplateSyntaxError as exc:
            result.problems.append(f"Błąd składni szablonu ({part}): {exc.message}")
            continue
        _Checker(allowed, result, part).stmts(tree.body, {})
    return result


def discover(docx_bytes: bytes) -> Validation:
    """Ścieżki i pola-listy, które czyta gotowy szablon (bez listy pól).
    ``problems`` zostają tylko dla konstrukcji spoza białej listy."""
    result = Validation()
    env = _env()
    for part, source in template_sources(docx_bytes):
        try:
            tree = env.parse(source)
        except TemplateSyntaxError as exc:
            result.problems.append(f"Błąd składni szablonu ({part}): {exc.message}")
            continue
        _Checker(allowed_paths([]), result, part, collect=True).stmts(tree.body, {})
    return result


def validate(docx_bytes: bytes, fields: list[CustomField]) -> Validation:
    """Walidacja całego pliku. Plik, którego nie da się otworzyć, też jest
    problemem (a nie wyjątkiem) — człowiek widzi komunikat przy wzorze."""
    try:
        sources = template_sources(docx_bytes)
    except DocxTooLarge as exc:
        return Validation(problems=[str(exc)])
    except Exception:  # noqa: BLE001 — uszkodzony plik od człowieka
        return Validation(problems=["Nie udało się otworzyć pliku Word (.docx)."])
    return validate_sources(sources, fields)


def render(
    docx_bytes: bytes,
    fields: list[CustomField],
    values: dict,
    *,
    language: str = "pl",
) -> bytes:
    """DOCX z wypełnionymi polami. Walidacja przed renderem; kontekst wyłącznie
    z pól z listy. Błąd szablonu → ``TemplateInvalid``."""
    check = validate(docx_bytes, fields)
    if check.problems:
        raise TemplateInvalid(check.problems)
    context = build_context(fields, values, language=language)
    check_package(docx_bytes)
    tpl = DocxTemplate(io.BytesIO(docx_bytes))
    tpl.render(context, jinja_env=_env(), autoescape=True)
    # Plik idzie do Partnera: bez autora z wgranego Worda.
    clear_author_metadata(tpl.docx)
    buf = io.BytesIO()
    tpl.save(buf)
    return clear_app_properties(buf.getvalue())
