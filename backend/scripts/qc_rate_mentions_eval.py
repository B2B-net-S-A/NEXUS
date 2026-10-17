"""„Stawka w CV” w QC trzema regułami — tylko odczyt, same liczby (17.10.2026).

Blokady `client_rules` nie da się pominąć, a rekruterzy zgłaszali „stawki”
w zdaniach bez stawki („Moduł wynagrodzeń dla 250 zleceniobiorców”). Skrypt
liczy QC raz na parę (`cv_qc.evaluate`, przebieg w ostatnich N dniach —
`QC_AUDIT_DAYS`, domyślnie 30) i na tych samych danych porównuje regułę stawki:

- `legacy` — luźne `_AMOUNT` przy słowie o pieniądzach (QC do 17.10.2026);
- `strict` — `money_text.is_rate_text` zdanie po zdaniu w oknie 80 znaków
  (to, co od PR #2290 usuwa „Usuń stawkę”);
- `cv` — `cv_qc.rate_mentions` z `money_text.is_cv_rate_text` (propozycja;
  jest tylko z nakładką `scripts/qc_overlay.py`, bez niej tej kolumny nie ma).

Wypisuje JSON: ile par i bloków ma „Stawkę w CV”, ile par zmieniłoby wynik
QC (blokada → zaliczone i odwrotnie) i cechy bloków, które w nowej regule
przestają albo zaczynają blokować — kwota z walutą jako osobnym słowem albo
kwota za czas w bloku, który przestaje blokować, to sygnał, że prawdziwa
stawka mogłaby przejść. Bez treści, nazw i identyfikatorów osób.
`QC_RATE_WORDS=1` dopisuje słowa, w których luźny wzorzec widział walutę
(„zleceniobiorców”), i słowa po liczbie w nowych blokadach — tylko te, które
stoją w co najmniej `WORDS_MIN` blokach, żeby nie wypisać fragmentu jednego CV.

Uruchomienie w kontenerze backendu (sesja bazy tylko do odczytu):
    python3 scripts/qc_overlay.py scripts/qc_rate_mentions_eval.py \\
        app/services/money_text.py app/services/cv_qc.py \\
      | ssh … "docker exec -i <backend> python -"
"""

import asyncio
import collections
import json
import os
import re

DAYS = int(os.environ.get("QC_AUDIT_DAYS", "30"))
WORDS = os.environ.get("QC_RATE_WORDS") == "1"
WORDS_MIN = 5

# Reguła sprzed propozycji — kopia, żeby pomiar działał też po merge'u.
_LEGACY_AMOUNT = re.compile(
    r"\d[\d\s.,]*\s*(?:z[łl]|pln|eur|€|usd|\$)(?:\s*/\s*(?:h|godz|md|dzie[nń]|mies))?"
    r"|\d[\d\s.,]*\s*/\s*(?:h|godz|md)\b",
    re.IGNORECASE,
)
_CURRENCY_WORD = re.compile(
    r"\d[\d\s.,]*\s*(?:(?:tys|mln)\b\.?\s*|k\s*)?(?:zł|zl|pln|euro|eur|usd|€|\$)(?!\w)"
    r"|[€$]\s*\d",
    re.IGNORECASE,
)
_RATE_THEN_NUMBER = re.compile(r"\b(?:stawk\w*|rate)\s*[:=]?\s*\d", re.IGNORECASE)
_GLUED = re.compile(r"\d[\d\s.,]*\s*((?:z[łl]|pln|eur|usd)\w+)", re.IGNORECASE)
_AFTER_NUMBER = re.compile(r"\d(?:[\d\s.,]*\d)?\s*(\S{0,12})")


def build_rules(cv_qc, money_text, base_qc=None) -> dict:
    """Reguły stawki po nazwie: blok CV → lista cytatów (jak `rate_mentions`).

    `strict` dzieli zdania tak jak dziś produkcja (`base_qc` — moduł z obrazu
    sprzed nakładki), bo ma pokazać, co dziś usuwa „Usuń stawkę”.
    """
    splitter = (base_qc or cv_qc)._SENTENCE_PIECE

    def legacy(blocks):
        return [
            b.text[:120]
            for b in blocks
            if money_text.RATE_WORD_RE.search(b.text) and _LEGACY_AMOUNT.search(b.text)
        ]

    def strict_sentence(piece: str) -> bool:
        for m in money_text.RATE_WORD_RE.finditer(piece):
            window = piece[max(0, m.start() - 80) : m.end() + 80]
            if money_text.is_rate_text(window):
                return True
        return False

    def strict(blocks):
        return [
            b.text[:120]
            for b in blocks
            if any(strict_sentence(m.group(0)) for m in splitter.finditer(b.text))
        ]

    rules = {"legacy": legacy, "strict": strict}
    if getattr(money_text, "is_cv_rate_text", None) is not None:
        # Propozycja: cały blok regułą „Usuń stawkę” — `rate_mentions` z gałęzi.
        rules["cv"] = cv_qc.rate_mentions
    return rules


async def main() -> None:
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal, engine
    from app.models.recruitment_pipeline import CandidateStage
    from app.services import cv_qc, money_text
    from app.services.skill_taxonomy_loader import refresh_alias_map

    await refresh_alias_map()
    base = globals().get("QC_OVERLAY_BASE", {}).get("app.services.cv_qc")
    rules = build_rules(cv_qc, money_text, base)

    real_compute = cv_qc.compute_checks
    real_mentions = cv_qc.rate_mentions
    captured: dict = {}

    def spy(data):
        captured["data"] = data
        return real_compute(data)

    def client_rules_with(rule, data) -> dict:
        cv_qc.rate_mentions = rule
        try:
            fresh = real_compute(data)
        finally:
            cv_qc.rate_mentions = real_mentions
        return next(c for c in fresh if c["key"] == "client_rules")

    stats: collections.Counter = collections.Counter()
    per_rule = {name: collections.Counter() for name in rules}
    changes: collections.Counter = collections.Counter()
    dropped: collections.Counter = collections.Counter()
    added: collections.Counter = collections.Counter()
    glued_words: collections.Counter = collections.Counter()
    after_words: collections.Counter = collections.Counter()
    errors: collections.Counter = collections.Counter()
    read_only = text("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
    cv_qc.compute_checks = spy
    async with AsyncSessionLocal() as db:
        # Ustawienie sesji działa od NASTĘPNEJ transakcji.
        await db.execute(read_only)
        await db.commit()
        stage_ids = (
            (
                await db.execute(
                    text(
                        "SELECT DISTINCT candidate_stage_id FROM cv_qc_runs "
                        "WHERE created_at > now() - make_interval(days => :days) "
                        "AND candidate_stage_id IS NOT NULL"
                    ),
                    {"days": DAYS},
                )
            )
            .scalars()
            .all()
        )
        for stage_id in stage_ids:
            try:
                stage = await db.get(CandidateStage, stage_id)
                if stage is None:
                    continue
                _src, checks, _notes = await cv_qc.evaluate(db, stage)
            except Exception as exc:  # noqa: BLE001 — pomiar liczy klasy błędów
                errors[type(exc).__name__] += 1
                await db.rollback()
                await db.execute(read_only)
                await db.commit()
                continue
            data = captured.pop("data", None)
            if data is None or not data.has_cv:
                stats["pairs_without_cv"] += 1
                continue
            stats["pairs"] += 1
            found = {name: set(rule(data.blocks)) for name, rule in rules.items()}
            passed = {}
            for name, rule in rules.items():
                check = client_rules_with(rule, data)
                # `client_rules` nie da się wyciszyć ani pominąć — podmiana tego
                # jednego sprawdzenia daje wynik po stanach i pominięciach.
                merged = [check if c["key"] == "client_rules" else c for c in checks]
                passed[name] = cv_qc.summarize(merged)[0]
                counter = per_rule[name]
                counter["pairs_with_rate"] += int(bool(found[name]))
                counter["rate_blocks"] += len(found[name])
                counter["client_rules_fail"] += int(check["status"] == "fail")
                counter["pairs_passed"] += int(passed[name])
            for name in rules:
                if name == "legacy":
                    continue
                if passed["legacy"] and not passed[name]:
                    changes[f"{name}:pass_to_fail"] += 1
                if not passed["legacy"] and passed[name]:
                    changes[f"{name}:fail_to_pass"] += 1
                if found["legacy"] and not found[name]:
                    changes[f"{name}:pairs_rate_gone"] += 1
                if found[name] and not found["legacy"]:
                    changes[f"{name}:pairs_rate_new"] += 1
                for block in found["legacy"] - found[name]:
                    dropped[f"{name}:blocks"] += 1
                    dropped[f"{name}:currency_word"] += int(
                        bool(_CURRENCY_WORD.search(block))
                    )
                    dropped[f"{name}:per_time"] += int(
                        any(
                            money_text._PER_TIME_RE.search(m.group())
                            for m in money_text.MONEY_RE.finditer(block)
                        )
                    )
                    dropped[f"{name}:rate_word_then_number"] += int(
                        bool(_RATE_THEN_NUMBER.search(block))
                    )
                    if WORDS:
                        glued_words.update(
                            {f"{name}:{w.lower()}" for w in _GLUED.findall(block)}
                        )
                for block in found[name] - found["legacy"]:
                    added[f"{name}:blocks"] += 1
                    added[f"{name}:currency_word"] += int(
                        bool(_CURRENCY_WORD.search(block))
                    )
                    if WORDS:
                        after_words.update(
                            {
                                f"{name}:{w.lower()}"
                                for w in _AFTER_NUMBER.findall(block)
                            }
                        )
    cv_qc.compute_checks = real_compute
    await engine.dispose()
    out = {
        "qc_version": cv_qc.QC_VERSION,
        "days": DAYS,
        "rules": list(rules),
        **stats,
        "per_rule": {name: dict(c) for name, c in per_rule.items()},
        "changes": dict(changes),
        "dropped_blocks": dict(dropped),
        "added_blocks": dict(added),
        "errors": dict(errors),
    }
    if WORDS:
        out["glued_words"] = {
            w: n for w, n in glued_words.most_common(30) if n >= WORDS_MIN
        }
        out["words_after_number"] = {
            w: n for w, n in after_words.most_common(30) if n >= WORDS_MIN
        }
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
