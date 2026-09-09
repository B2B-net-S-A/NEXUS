"""Resolve formatting independently of narrative mode; never add CV facts."""

import re
from typing import Any

from app.services.cv_generator_b2b.client_rules import CvRuleSnapshot
from app.services.cv_generator_b2b.docx_renderer import (
    compile_keyword_patterns,
    highlight_spans,
)


def apply_highlight_policy(
    data: dict[str, Any],
    rule: CvRuleSnapshot | None,
    source_text: str,
    must: list[str],
    nice: list[str],
) -> None:
    policy = rule.highlight_policy if rule else "technologies"
    if policy == "none":
        requested = []
    elif policy == "must":
        requested = list(must)
    elif policy == "must_nice":
        requested = [*must, *nice]
    elif policy == "explicit":
        requested = list(rule.highlight_terms) if rule else []
    else:
        requested = [
            tech
            for job in data.get("experience", [])
            for tech in job.get("technologies", [])
        ]
        requested.extend(
            term.strip()
            for group in data.get("skills", [])
            for term in re.split(r"[,;\n]", group.get("content", ""))
            if term.strip()
        )
    requested = list(dict.fromkeys(requested))
    selected, ignored = [], []
    for term in requested:
        patterns = compile_keyword_patterns([term])
        if patterns and highlight_spans(source_text, patterns):
            selected.append(term)
        else:
            ignored.append(term)
    data["highlight_keywords"] = selected
    # Private diagnostics: public projection includes only selected keywords.
    data["highlight_policy_result"] = {
        "policy": policy,
        "selected": selected,
        "ignored": ignored,
        "requires_champion": (policy == "must" and not must)
        or (policy == "must_nice" and not (must or nice)),
    }
