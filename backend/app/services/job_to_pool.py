"""Deterministic Job/Candidate → Talent-Pool classifier + resolver.

Maps a role signal (a Job title, optionally enriched with the candidate's own
skill tokens) to ONE pool from the live, curated catalogue of role pools
imported from Traffit ("Java", "DevOps Engineer - Azure",
"Manual Tester (web, mob, sys (bankowość)", "Business Analyst - Payments", …).
Used to populate talent pools from the ``cv_sent`` ("CV wysłane do klienta")
signal — both at the live stage-move trigger (``talent_pool_auto_add``) and in
the historical backfill (``services.talent_pool_backfill``).

Why title-first, CC second
--------------------------
On production, jobs carry no ``subcategory`` / ``seniority`` (the Traffit import
left them NULL), so the original pool-name derivation in
``talent_pool_auto_add`` skipped ~100 % of ``cv_sent`` moves — 8 400+
sent-to-client candidates produced ~0 pool memberships. Job *titles*, however,
are a controlled-ish vocabulary of role names and reliably carry the role token
("Java Developer", "Manual Tester", "DevOps", "Scrum Master"). The job's
``competence_category_id`` is itself derived from the title and is sometimes
wrong (e.g. "Senior JAVA Developer, OBH" got tagged ``management_delivery``), so
CC is *not* used as a gate here — the title token decides.

Precision over recall
----------------------
A wrong candidate in a pool wastes a recruiter's sourcing time, so:
  * rules are ordered most-specific-first (QA/security → data → management →
    infrastructure → software), mirroring ``services.job_cc``;
  * a title that only names a *family* without the distinguishing token
    (a bare "Developer", an "Automation Tester" with no language) resolves to
    ``None`` (skip) rather than guessing a variant;
  * the candidate's own skills can supply the missing token — a bare
    "Test Automation Engineer" whose CV lists Cypress resolves to the Cypress
    pool. Skills are consulted ONLY when the title alone is inconclusive, so
    they never override a clear title (a "Manual Tester" job stays a manual
    pool even if the candidate also knows Selenium).

The full name→pool expectation across the live catalogue is locked by
``tests/test_job_to_pool.py``.
"""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.talent_pool import TalentPool

# Sentinel returned by the rule table for "this is clearly an automation-test
# role but the variant (language) is undeterminable from the signal" — callers
# treat it exactly like None (skip), but keeping it distinct lets the rule order
# stop a bare automation title from falling through to the manual-tester rule.
_SKIP = "__SKIP__"

# Distinct object so internal helpers can tell "matched the skip sentinel" from
# "matched nothing" without leaking the raw string to callers.
_SKIP_RESULT = object()

# Canonical pool names — MUST match the live catalogue verbatim (incl. the
# unbalanced paren in the Manual-Tester name). Resolution is case-insensitive.
P_MANUAL_GENERAL = "Manual Tester (web, mob, sys (bankowość)"
P_MANUAL_DB = "Manual Tester - bazy danych"

# Ordered (pool_name, patterns) rules — the FIRST pool with any matching pattern
# wins. Patterns are case-insensitive regexes; short / ambiguous tokens use
# ``\b`` word-boundary anchors. ``_SKIP`` entries deliberately short-circuit.
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # ════════════════════════════════════════════════════════════════════
    # 1) QUALITY / SECURITY — checked first so a "Java tester (Selenium)"
    #    stays a QA pool (not the Java dev pool) and "Test Architect" stays QA.
    # ════════════════════════════════════════════════════════════════════
    # Performance testing (named tools win over generic automation).
    (
        "Performance Tester (jMeter, Loadrunner, Gatling)",
        (r"performance test", r"\bjmeter\b", r"loadrunner", r"\bgatling\b"),
    ),
    # Automation testing — language/framework-specific variants. A title or
    # skill blob must name the tooling; otherwise we hit the _SKIP rule below.
    (
        "Tester Automatyzujący (Cypress, JavaScript)",
        (r"\bcypress\b",),
    ),
    (
        "Tester Automatyzujący (Playwright, TypeScript)",
        (r"\bplaywright\b",),
    ),
    (
        "Tester Automatyzujący (Python, Robot Framework)",
        (r"robot\s*framework",),
    ),
    (
        "Tester Automatyzujący (Python, PyTest)",
        (r"\bpytest\b",),
    ),
    (
        "Tester Automatyzujący (C#, Selenium)",
        (
            r"selenium.{0,20}(c#|c\s?sharp|\.net)",
            r"(c#|c\s?sharp|\.net).{0,20}selenium",
        ),
    ),
    (
        "Tester Automatyzujący (ETL, bazy danych)",
        (
            r"\betl\b.{0,30}(test|tester)",
            r"(test|tester).{0,30}\betl\b",
        ),
    ),
    (
        "Tester Automatyzujący (Java, Selenium)",
        (r"\bselenium\b",),  # default Selenium flavour (Java) when no C#/.NET token
    ),
    # Embedded testing.
    ("Tester embedded", (r"tester embedded", r"embedded test")),
    # QA leadership roles (before the generic "tester" rule).
    ("Test Architect", (r"test architect", r"architekt test")),
    ("Test Manager", (r"test manager", r"kierownik test", r"menad\w*er test")),
    ("Test Lead", (r"test lead", r"lead tester", r"\be2e test lead\b", r"lider test")),
    # Generic automation testing with NO language anywhere → cannot pick a
    # variant safely. Skip rather than dump into an arbitrary language pool (or
    # into the manual-tester catch below). The proximity / "(automation)" forms
    # catch "QA Test Engineer Senior (automation)" without snagging RPA /
    # "Power Automate" (no test/qa token near "automation" there).
    (
        _SKIP,
        (
            r"automation test",
            r"test automation",
            r"automation engineer",
            r"tester automatyzuj",
            r"tester automatyczn",
            r"automatyzacja test",
            r"\(automation\)",
            r"\btest\b.{0,25}\bautomation\b",
            r"\bautomation\b.{0,25}\b(test|tester|qa)\b",
            r"\b(qa|test|tester)\b.{0,25}\bautomation\b",
        ),
    ),
    # Security roles.
    ("Pentester (blue+red)", (r"pentest", r"penetration", r"red team", r"blue team")),
    (
        "IAM Engineer, Vulnerability Management",
        (
            r"\biam\b",
            r"identity and access",
            r"vulnerability manag",
            r"zarz\w* podatno",
        ),
    ),
    ("SOC", (r"\bsoc\b", r"security operations cent")),
    (
        "Security Engineer",
        (
            r"security engineer",
            r"security specialist",
            r"security architect",
            r"cyber\s?security",
            # ``\b`` anchor keeps this off "ubezpieczeń"/"ubezpieczenie"
            # (insurance), which embeds "bezpiecze" mid-word.
            r"\bbezpiecze",
            r"\bfirewall\b",
            r"zero trust",
            r"\bappsec\b",
            r"\bsiem\b",
        ),
    ),
    # Generic manual / unspecified tester → the general Manual pool (the largest
    # QA bucket). Database-flavoured manual testing gets its own pool.
    (
        P_MANUAL_DB,
        (r"(manual test|tester manualn).{0,30}(baz danych|database|\bsql\b)",),
    ),
    (
        P_MANUAL_GENERAL,
        (
            r"manual test",
            r"tester manualn",
            r"\bqa engineer\b",
            r"\bqa\b",
            r"\btester\b",
            r"\btesters\b",
            r"test engineer",
            r"\btestów\b",
        ),
    ),
    # ════════════════════════════════════════════════════════════════════
    # 2) DATA & AI
    # ════════════════════════════════════════════════════════════════════
    ("Data Scientist", (r"data scientist", r"data science")),
    ("Data Engineer", (r"data engineer", r"in\w*ynier danych")),
    ("Data Architect", (r"data architect", r"architekt danych")),
    ("MLOps Engineer", (r"mlops", r"\bml ops\b")),
    (
        "ML Infrastructure Engineer",
        (r"\bml\b infrastructure", r"machine learning infra"),
    ),
    (
        "AI Engineer",
        (
            r"\bai\b engineer",
            r"\bai/ml\b",
            r"\bnlp\b",
            r"\bllm\b",
            r"gen\w*\s*ai",
            r"machine learning",
            r"deep learning",
            r"\bml engineer\b",
        ),
    ),
    ("BIG DATA (Hadoop)", (r"big data", r"\bhadoop\b", r"\bspark\b")),
    # ════════════════════════════════════════════════════════════════════
    # 3) MANAGEMENT & DELIVERY — analysts, PM/PO, scrum, the "* Manager"
    #    family. Checked before infrastructure (Service Manager ≠ Service Desk).
    # ════════════════════════════════════════════════════════════════════
    (
        "Scrum Master / Agile Coach",
        (r"scrum master", r"agile coach", r"\bscrum\b", r"zespó\w* scrum"),
    ),
    ("RTE - Release Train Engineer", (r"release train", r"\brte\b")),
    ("Product Owner", (r"product owner",)),
    ("Program Manager", (r"program manager", r"kierownik programu")),
    (
        "IT Project Manager",
        (
            r"project manager",
            r"kierownik projekt",
            r"menad\w*er projekt",
            r"mened\w*er projekt",
            r"\bit pm\b",
        ),
    ),
    (
        "PMO",
        (r"\bpmo\b", r"team planner", r"project assistant", r"koordynator projekt"),
    ),
    ("Change Manager", (r"change manager", r"kierownik\b.{0,20}zmian")),
    ("Migration Manager", (r"migration manager",)),
    ("Transition Manager", (r"transition manager",)),
    ("Rollout / Release Manager", (r"release manager", r"\brollout\b")),
    ("Service Manager", (r"service manager",)),
    ("Risk / GRC Manager", (r"\bgrc\b", r"risk manager", r"operational risk")),
    ("DORA Specialist", (r"\bdora\b",)),
    ("Compliance Specialist", (r"compliance",)),
    # Business Analyst — domain variants before the generic BA.
    (
        "Business Analyst - Financial Crime / AML",
        (
            r"(business analyst|analityk biznes).{0,40}(aml|financial crime|anti.?money)",
        ),
    ),
    (
        "Business Analyst - Payments",
        (r"(business analyst|analityk biznes).{0,40}payment",),
    ),
    (
        "Business Analyst - Mortgage / Credit",
        (r"(business analyst|analityk biznes).{0,40}(mortgage|credit|kredyt|hipotek)",),
    ),
    (
        "Business Analyst - Regulatory / Compliance",
        (r"(business analyst|analityk biznes).{0,40}(regulat|compliance|regulacyj)",),
    ),
    ("Business Analyst - General", (r"business analyst", r"analityk biznesow")),
    # IT Analyst — focus variants then the generic analyst default.
    (
        "IT Analyst - Data Focus",
        (r"data analyst", r"analityk danych", r"it analyst.{0,20}data"),
    ),
    (
        "IT Analyst - Systems / Integration Focus",
        (
            r"analityk systemow",
            r"system analyst",
            r"systems analyst",
            r"integration analyst",
            r"analityk integ",
            r"it analyst.{0,20}(system|integration)",
        ),
    ),
    ("Lead IT Analyst", (r"lead it analyst", r"lead analyst", r"g\w*ówny analityk")),
    (
        "IT Analyst - Business Focus",
        (r"\bit analyst\b", r"analityk it", r"\banalityk\b", r"\banalyst\b"),
    ),
    # ════════════════════════════════════════════════════════════════════
    # 4) INFRASTRUCTURE & OPERATIONS
    # ════════════════════════════════════════════════════════════════════
    (
        "DevOps Engineer - Azure",
        (r"(dev[\s-]?ops|\bsre\b).{0,30}azure", r"azure.{0,30}dev[\s-]?ops"),
    ),
    (
        "DevOps Engineer AWS",
        (r"(dev[\s-]?ops|\bsre\b).{0,30}\baws\b", r"\baws\b.{0,30}dev[\s-]?ops"),
    ),
    ("SRE/DevOps (bez chmury)", (r"dev[\s-]?ops", r"\bsre\b")),
    ("Cloud Architect", (r"cloud architect", r"architekt chmur")),
    ("Network Architect", (r"network architect", r"architekt sieci")),
    ("Network Engineer", (r"network engineer", r"in\w*ynier sieci")),
    ("Network Administrator", (r"network admin", r"administrator sieci")),
    ("NOC Engineer", (r"\bnoc\b",)),
    (
        "Helpdesk L3",
        (r"helpdesk.{0,10}(l3|3rd|\biii\b)", r"3rd line", r"3 lini\w* wsparci"),
    ),
    (
        "Helpdesk L2",
        (
            r"helpdesk.{0,10}(l2|2nd|\bii\b)",
            r"2nd line",
            r"2 lini\w* wsparci",
            r"ii lini\w* wsparci",
        ),
    ),
    (
        "Helpdesk L1",
        (r"helpdesk.{0,10}(l1|1st|\bi\b)", r"1st line", r"1 lini\w* wsparci"),
    ),
    (
        "Service Desk",
        (
            r"service desk",
            r"\bhelpdesk\b",
            r"user support",
            r"wsparci\w*\s+u\w*ytkownik",
            r"specjalista wsparcia",
        ),
    ),
    ("Cloud Engineer", (r"cloud engineer", r"\bcloud\b", r"\bchmur")),
    ("Oracle DBA", (r"oracle dba", r"oracle database", r"oracle db\b")),
    ("MS DBA", (r"(ms ?sql|sql server|mssql).{0,15}dba", r"\bms dba\b", r"sql server")),
    ("Linux Admin", (r"\blinux\b",)),
    ("Windows Admin", (r"windows admin", r"administrator windows")),
    ("Virtualization Engineer", (r"virtualization", r"wirtualizacj", r"\bvmware\b")),
    ("Mainframe", (r"mainframe", r"\bz/os\b")),
    ("Infrastructure Engineer", (r"infrastructure engineer", r"infrastruktur")),
    ("Platform Engineer", (r"platform engineer",)),
    # ════════════════════════════════════════════════════════════════════
    # 5) SOFTWARE DEVELOPMENT — language / framework. FullStack variants before
    #    the single-language pools so "FullStack Java" ≠ "Java".
    # ════════════════════════════════════════════════════════════════════
    ("FullStack Java", (r"full[\s-]?stack.{0,15}java", r"java.{0,15}full[\s-]?stack")),
    (
        "FullStack .NET",
        (
            r"full[\s-]?stack.{0,15}(\.net|c#|dotnet)",
            r"(\.net|c#|dotnet).{0,15}full[\s-]?stack",
        ),
    ),
    (
        "FullStack JS",
        (
            r"full[\s-]?stack.{0,15}(js|javascript|node|react|angular)",
            r"(js|javascript|node|react|angular).{0,15}full[\s-]?stack",
        ),
    ),
    # ``\bnet\b`` catches the dotless Polish spelling "Programista NET"; the word
    # boundaries keep it off "Netbank" / "Network" (no trailing boundary there).
    (
        ".NET (C#)",
        (r"\.net\b", r"\bnet\b", r"dotnet", r"\bc#", r"\bc\s?sharp\b", r"asp\.net"),
    ),
    ("Java", (r"\bjava\b",)),  # \bjava\b won't match "javascript"
    ("Angular", (r"\bangular\b",)),
    ("React", (r"\breact\b",)),
    ("Vue.js", (r"\bvue\b", r"vue\.js")),
    ("Node.Js", (r"node\.?js", r"\bnode\b")),
    ("GO", (r"\bgolang\b", r"\bgo\b\s+develop", r"develop\w*\s+\bgo\b")),
    ("Python", (r"\bpython\b",)),
    ("PHP", (r"\bphp\b",)),
    ("C/C++", (r"c\+\+", r"c/c\+\+")),
    ("COBOL", (r"\bcobol\b",)),
    ("ABAP DEV", (r"\babap\b",)),
    ("iOS", (r"\bios\b", r"\bswift\b")),
    ("Android", (r"\bandroid\b", r"\bkotlin\b")),
    (
        "UX/UI",
        (r"\bux\b", r"ui\s*/\s*ux", r"ux\s*/\s*ui", r"ui designer", r"projektant ui"),
    ),
    ("RPA", (r"\brpa\b", r"uipath", r"blue prism", r"power automate")),
    (
        "Powerapps (Power Platform, Dynamics)",
        (r"power\s?apps", r"power platform", r"\bdynamics\b"),
    ),
    ("Low Code", (r"low[\s-]?code",)),
    ("SAP Consultant", (r"\bsap\b",)),
    ("PEGA", (r"\bpega\b",)),
    ("ERP", (r"\berp\b",)),
    ("Enterprise Architect", (r"enterprise architect", r"architekt korporacyj")),
    (
        "System Architect",
        (
            r"system architect",
            r"solution architect",
            r"architekt system",
            r"architekt rozwi",
        ),
    ),
)

_COMPILED: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (name, tuple(re.compile(p, re.IGNORECASE) for p in pats)) for name, pats in _RULES
)


def _normalize(text: Optional[str]) -> str:
    """Lowercase + flatten separators so ``\b`` anchors behave on prod titles.

    Prod titles use "_" as a separator ("PL_Senior_Java_Developer") and "/" to
    glue tokens ("Full Stack/ Java") — both would defeat word boundaries on the
    short language tokens, so we turn them into spaces and collapse runs.
    """
    if not text:
        return ""
    t = text.lower().replace("_", " ")
    # Keep "c#", "c++", "/" inside "c/c++" and "ui/ux"; collapse whitespace only.
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _match(text: str):
    """Return canonical pool name (str), the ``_SKIP_RESULT`` sentinel, or None."""
    if not text:
        return None
    for name, patterns in _COMPILED:
        if any(p.search(text) for p in patterns):
            return _SKIP_RESULT if name == _SKIP else name
    return None


def classify_role_to_pool_name(
    title: Optional[str], *, skill_text: Optional[str] = None
) -> Optional[str]:
    """Map a role signal to a canonical pool name, or ``None`` if inconclusive.

    Pure and deterministic — no DB / network. ``title`` is matched first; only
    when the title alone is inconclusive (no rule matched, or an ambiguous
    automation role hitting the skip sentinel) is ``skill_text`` appended and the
    blob re-matched, so a clear title is never overridden by the candidate's
    secondary skills.
    """
    title_name = _match(_normalize(title))
    if isinstance(title_name, str):
        return title_name
    # title_name is now either None (no match) or _SKIP_RESULT (ambiguous
    # automation). Either way, try skills to recover a specific variant.
    if not skill_text:
        return None
    combined_name = _match(_normalize(f"{title or ''} {skill_text}"))
    return combined_name if isinstance(combined_name, str) else None


def _candidate_skill_text(candidate) -> str:
    """Build a bounded skill/role text blob from a Candidate for fallback match.

    Defensive against the messy shapes seen on prod: ``skills`` may be a list of
    ``{"name": ...}`` dicts, a list of strings, a JSON-encoded string, or NULL
    (see [[project_matching_skills_stringified]]). We also fold in tags and the
    LinkedIn / current title which often name the actual stack.
    """
    if candidate is None:
        return ""
    parts: list[str] = []

    def _add_skills(raw) -> None:
        if raw is None:
            return
        if isinstance(raw, str):
            parts.append(raw)
            return
        if isinstance(raw, dict):
            raw = list(raw.values())
        if isinstance(raw, (list, tuple)):
            for item in raw:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("skill") or item.get("label")
                    if isinstance(name, str):
                        parts.append(name)

    _add_skills(getattr(candidate, "skills", None))
    _add_skills(getattr(candidate, "tags", None))
    for attr in ("linkedin_current_title", "current_position", "headline", "title"):
        val = getattr(candidate, attr, None)
        if isinstance(val, str) and val.strip():
            parts.append(val)
    # Bound the blob so a pathological CV can't blow up the regex pass.
    return " ".join(parts)[:2000]


async def resolve_pool_for_cv_sent(
    db: AsyncSession, *, job, candidate=None
) -> Optional[TalentPool]:
    """Resolve the EXISTING talent pool a cv_sent candidate belongs to.

    Title-first classification against the curated catalogue; the candidate's
    skills are consulted only when the title is inconclusive. Returns the live
    ``TalentPool`` row (matched case-insensitively by name) or ``None`` when no
    confident match exists or the canonical pool is absent from the catalogue.

    This NEVER creates a pool — the catalogue is the curated set of role pools;
    creating ad-hoc name variants is what left the taxonomy fragmented before.
    """
    title = getattr(job, "title", None)
    skill_text = _candidate_skill_text(candidate) if candidate is not None else None
    pool_name = classify_role_to_pool_name(title, skill_text=skill_text)
    if pool_name is None:
        return None
    # Target a COMPANY pool only. Pool names aren't unique, so without the
    # is_personal / is_marketplace filter a personal pool with a colliding name
    # (e.g. "Java") would be mutated by a cv_sent trigger, bypassing the
    # _assert_can_modify_pool ownership gate (migracja 0137).
    return await db.scalar(
        select(TalentPool).where(
            func.lower(TalentPool.name) == pool_name.lower(),
            TalentPool.is_personal.is_(False),
            TalentPool.is_marketplace.is_(False),
        )
    )
