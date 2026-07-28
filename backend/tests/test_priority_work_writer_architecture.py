"""Architecture fence for the canonical CandidateStage command path."""

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"
COMMAND_WRITER = APP_ROOT / "services" / "recruitment_process_commands.py"
RAW_ADAPTER = APP_ROOT / "services" / "traffit" / "importer.py"
RAW_METADATA_ADAPTER = APP_ROOT / "services" / "traffit" / "rejection_backfill.py"
ROOT_RUNTIME_WRITERS = (
    BACKEND_ROOT / "seed.py",
    BACKEND_ROOT / "seed_v6_pipeline.py",
)


def _python_files() -> list[Path]:
    return sorted([*APP_ROOT.rglob("*.py"), *ROOT_RUNTIME_WRITERS])


def _display_path(path: Path) -> str:
    return str(path.relative_to(BACKEND_ROOT))


def _is_candidate_stage_constructor(call: ast.Call) -> bool:
    function = call.func
    return isinstance(function, ast.Name) and function.id == "CandidateStage"


def _is_sqlalchemy_candidate_stage_insert(call: ast.Call) -> bool:
    function = call.func
    is_insert = (
        isinstance(function, ast.Name)
        and function.id in {"insert", "bulk_insert_mappings"}
    ) or (
        isinstance(function, ast.Attribute)
        and function.attr in {"insert", "bulk_insert_mappings"}
    )
    if not is_insert:
        return False
    return any(
        isinstance(argument, ast.Name) and argument.id == "CandidateStage"
        for argument in call.args
    )


def _is_sqlalchemy_candidate_stage_update_or_delete(call: ast.Call) -> bool:
    function = call.func
    is_mutation = (
        isinstance(function, ast.Name) and function.id in {"update", "delete"}
    ) or (isinstance(function, ast.Attribute) and function.attr in {"update", "delete"})
    if not is_mutation:
        return False
    return any(
        isinstance(argument, ast.Name) and argument.id == "CandidateStage"
        for argument in call.args
    )


_CRITICAL_STAGE_FIELDS = {
    "stage",
    "stage_def_id",
    "verification_status",
    "approved_by",
    "approved_at",
    "rejected_by",
    "rejected_at",
    "rejection_note",
    "expected_rate_value",
    "expected_rate_unit",
    "expected_rate_currency",
    "client_rate_value",
    "client_rate_unit",
    "client_rate_currency",
    "budget_max_at_move",
    "sla_alerted_at",
}


def _assignment_targets(node: ast.AST) -> list[ast.expr]:
    if isinstance(node, ast.Assign):
        return node.targets
    if isinstance(node, ast.AnnAssign):
        return [node.target]
    if isinstance(node, ast.AugAssign):
        return [node.target]
    return []


def test_candidate_stage_has_one_native_constructor() -> None:
    violations: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (
                _is_candidate_stage_constructor(node)
                or _is_sqlalchemy_candidate_stage_insert(node)
            ):
                continue
            if path != COMMAND_WRITER:
                violations.append(f"{_display_path(path)}:{node.lineno}")
    assert violations == [], (
        "CandidateStage writes must use recruitment_process_commands; "
        f"found direct writers: {violations}"
    )


def test_only_traffit_adapter_may_use_raw_candidate_stage_insert() -> None:
    violations: list[str] = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        if "insert into candidate_stages" not in source.lower():
            continue
        if path != RAW_ADAPTER:
            violations.append(_display_path(path))
    assert violations == [], (
        "Raw candidate_stages INSERT is allowed only in the Traffit adapter: "
        f"{violations}"
    )

    adapter_source = RAW_ADAPTER.read_text(encoding="utf-8")
    assert "sync_external_observed_processes" in adapter_source, (
        "The Traffit raw adapter must reconcile every imported pair into "
        "RecruitmentProcess in the same batch workflow."
    )


def test_candidate_stage_update_delete_and_critical_fields_use_command_writer() -> None:
    violations: list[str] = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (
                _is_sqlalchemy_candidate_stage_update_or_delete(node)
            ):
                if path != COMMAND_WRITER:
                    violations.append(f"{_display_path(path)}:{node.lineno}")
            if path == COMMAND_WRITER or "CandidateStage" not in source:
                continue
            for target in _assignment_targets(node):
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr in _CRITICAL_STAGE_FIELDS
                ):
                    violations.append(f"{_display_path(path)}:{node.lineno}")
    assert violations == [], (
        "CandidateStage lifecycle/critical metadata mutations must use "
        f"recruitment_process_commands; found: {violations}"
    )


def test_raw_candidate_stage_update_is_only_the_traffit_metadata_adapter() -> None:
    violations: list[str] = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8").lower()
        if "update candidate_stages" not in source:
            continue
        if path != RAW_METADATA_ADAPTER:
            violations.append(_display_path(path))
    assert violations == [], (
        "Raw candidate_stages UPDATE is allowed only for the idempotent "
        f"Traffit metadata adapter: {violations}"
    )


def test_demo_seed_never_deletes_pipeline_or_process_history() -> None:
    source = (BACKEND_ROOT / "seed_v6_pipeline.py").read_text(encoding="utf-8")
    assert "delete(CandidateStage)" not in source
    assert "delete(RecruitmentProcess)" not in source
    assert "Preserving" in source


def test_every_policy_checked_process_ingress_declares_its_work_channel() -> None:
    violations: list[str] = []
    for path in _python_files():
        if path == COMMAND_WRITER:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr
                if isinstance(function, ast.Attribute)
                else None
            )
            if name not in {"open_process", "transition_process"}:
                continue
            keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            if "work_channel" in keywords:
                continue
            if "require_existing" in keywords:
                continue
            origin = (
                ast.unparse(keywords.get("origin_kind"))
                if "origin_kind" in keywords
                else ""
            )
            if origin.endswith(".external_inbound") or origin.endswith(
                ".external_observed"
            ):
                continue
            violations.append(f"{_display_path(path)}:{node.lineno}")
    assert violations == [], (
        "Every human process ingress must declare database/linkedin channel; "
        f"found: {violations}"
    )
