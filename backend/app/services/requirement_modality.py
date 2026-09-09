"""Conservative Polish/English requirement modality; no remote calls.

Skill recognition is supplied by the canonical taxonomy. Unknown modality is
reported for human review, never silently promoted to a hard requirement.
"""

import re

_MARKERS = re.compile(
    r"\b(?:(?P<excluded>nie\s+(?:wymagamy|wymagane|jest\s+wymagan\w*)|niewymagan\w*|"
    r"not\s+required|no\s+(?:need|requirement)\s+for|without\s+requiring)|"
    r"(?P<nice>mile\s+widzian\w*|opcjonaln\w*|dodatkowym\s+atutem|"
    r"nice[ -]to[ -]have|optional|preferred|a\s+plus)|"
    r"(?P<must>wymagan\w*|wymagamy|obowiązkow\w*|konieczn\w*|"
    r"must(?:[ -]have)?|required|requirements|essential))\b",
    re.IGNORECASE,
)


def classify_requirements(text: str, pattern, aliases: dict) -> dict[str, list[str]]:
    buckets = {key: set() for key in ("must", "nice", "excluded", "uncertain")}
    if pattern is None:
        return {key: [] for key in buckets}
    # Do not split dots inside technology names (.NET, Node.js).
    clauses = re.split(r"(?:[.!?;]\s+|\n)", text)
    section = "uncertain"
    alternatives = []
    singletons = {key: set() for key in buckets}
    for clause in clauses:
        if not clause.strip():
            section = "uncertain"
            continue
        markers = list(_MARKERS.finditer(clause))
        matches = list(pattern.finditer(clause))
        occurrences = []
        for match in matches:
            before = [m for m in markers if m.end() <= match.start()]
            after = [m for m in markers if m.start() >= match.end()]
            kind = before[-1].lastgroup if before else section
            # "Java is not required" and "Python — optional".
            if after and not pattern.search(clause[match.end() : after[0].start()]):
                between = clause[match.end() : after[0].start()].strip(" :—-()")
                if between.lower() in {"", "is", "jest"}:
                    kind = after[0].lastgroup
            name = aliases.get(match.group(1).lower())
            if name:
                buckets[kind].add(name)
                occurrences.append((match.start(), match.end(), name, kind))
        groups = []
        for occurrence in occurrences:
            if (
                groups
                and occurrence[3] == groups[-1][-1][3]
                and re.fullmatch(
                    r"\s+(?:or|lub|albo)\s+",
                    clause[groups[-1][-1][1] : occurrence[0]],
                    re.IGNORECASE,
                )
            ):
                groups[-1].append(occurrence)
            else:
                groups.append([occurrence])
        for group in groups:
            names = list(dict.fromkeys(item[2] for item in group))
            if len(names) > 1:
                alternatives.append((group[0][3], names))
            elif names:
                singletons[group[0][3]].add(names[0])
        # Headers apply to following bullet lines; prose sentences do not.
        if markers and (not matches or clause.rstrip().endswith(":")):
            section = markers[-1].lastgroup
    # Conflicting evidence stays reviewable instead of guessing precedence.
    for name in set().union(*buckets.values()):
        kinds = [key for key in ("must", "nice", "excluded") if name in buckets[key]]
        if len(kinds) > 1:
            for key in kinds:
                buckets[key].discard(name)
            buckets["uncertain"].add(name)
        elif kinds:
            buckets["uncertain"].discard(name)
    valid_alternatives = [
        (kind, names)
        for kind, names in alternatives
        if all(name in buckets[kind] for name in names)
    ]
    for kind, names in valid_alternatives:
        if names:
            for name in names:
                if name not in singletons[kind]:
                    buckets[kind].discard(name)
            buckets[kind].add(" lub ".join(names))
    return {key: sorted(values) for key, values in buckets.items()}
