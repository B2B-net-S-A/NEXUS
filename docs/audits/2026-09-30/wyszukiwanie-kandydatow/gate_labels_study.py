"""Które etykiety must bramkują i ile osób wysłanych do klienta ukrywają (cała historia).

Dla każdej rekrutacji z ≥3 osobami wysłanymi: etykiety z `search_dealbreaker_inputs`,
dowód v8 (lista, profil, CV, notatki-rozmowy SPRZED otwarcia rekrutacji). Klasyfikacja
etykiety: `taxonomy_role_category` (przeszła tylko dlatego, że nazwa jest w słowniku
umiejętności, a reguła rola/kategoria by ją odrzuciła), `example_prose` (opcje wyjęte
z nawiasu/„np.” po zdaniu, które samo nie jest technologią), `plain`.
Plus: otwarte rekrutacje w pracy — ile ma takie etykiety.
Tylko odczyt.
"""
import ro_boot  # noqa: F401
import asyncio, json, statistics, time
from collections import defaultdict, Counter
import data


async def main():
    await data.boot()
    from sqlalchemy import select, text
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.services.requirement_contract import search_dealbreaker_inputs
    from app.services.dealbreaker_filters import missing_must_skills
    from app.services.must_text_evidence import MustTextEvidence, text_met_labels
    from app.services import must_gate_terms as mg
    from app.services.skill_normalize import is_taxonomy_technology

    def label_kind(label):
        req = mg.gate_requirement(label)
        if req is None:
            return None
        text_ = mg._clean(label)
        text_ = mg.strip_version(text_)[0]
        ex = mg._EXAMPLES.match(text_) or mg._PAREN_LIST.match(text_)
        if ex:
            head = mg._clean(ex.group("head")).strip("(:-–— ")
            hn, _ = mg._normalize_option(" ".join(w for w in head.split() if w.lower() not in mg._CATEGORY_WORDS))
            if not hn and not all(is_taxonomy_technology(o) for o in req.options):
                return "example_prose"
            return "example"
        for o in req.options:
            if mg._option_reason(o) in ("role", "category", "prose", "domain", "soft", "language"):
                return "taxonomy_role_category"
        return "plain"

    pos = await data.load_positives()
    jobs = {j.id: j for j in await data.load_jobs()}
    work = []
    for jid, P in pos.items():
        j = jobs.get(jid)
        if not j or j.external_source == "manual":
            continue
        sent = [c for c, r in P.items() if r >= 1]
        if len(sent) >= 3:
            must = list(search_dealbreaker_inputs(j).must_skills)
            if must:
                work.append((jid, must, sent))
    need = sorted({c for _, _, s in work for c in s})
    print(f"jobs={len(work)} people={len(need)}", flush=True)
    cobj, notes = {}, defaultdict(list)
    async with AsyncSessionLocal() as db:
        for i in range(0, len(need), 1000):
            for c in (await db.execute(select(Candidate).where(Candidate.id.in_(need[i:i+1000])))).scalars().all():
                db.expunge(c); cobj[c.id] = c
            for cid, at, content in (await db.execute(text(
                "SELECT candidate_id, created_at, content FROM notes WHERE candidate_id = ANY(:ids) AND source_deleted_at IS NULL "
                "AND note_type::text = ANY(:t)"), {"ids": need[i:i+1000], "t": ["call", "meeting", "general", "interview"]})).all():
                notes[cid].append((at, content or ""))
        open_jobs = (await db.execute(text(
            "SELECT id FROM jobs WHERE status='published' AND coalesce(work_state,'to_review') IN ('searching','to_review','client_silent')"))).all()
    lab = defaultdict(lambda: [0, 0, 0])  # label -> [met, total, jobs]
    kinds = {}
    hidden_by_kind = Counter(); hidden_any = 0; total = 0
    hidden_fixed = 0
    t0 = time.time()
    for n, (jid, must, sent) in enumerate(work):
        j = jobs[jid]; cutoff = j.opened_at or j.created_at
        for l in must:
            kinds.setdefault(l, label_kind(l))
            lab[l][2] += 1
        good = [l for l in must if kinds[l] in ("plain", "example")]
        for cid in sent:
            c = cobj.get(cid)
            if c is None:
                continue
            nts = [t for (at, t) in notes.get(cid, ()) if cutoff is None or at < cutoff]
            met = text_met_labels(c, must, nts)
            c._must_text_evidence = MustTextEvidence(key=tuple(must), met=met, has_notes=bool(nts))
            miss = set(missing_must_skills(c, must))
            total += 1
            if miss:
                hidden_any += 1
                for k in {kinds[l] for l in miss}:
                    hidden_by_kind[k] += 1
            if miss & set(good):
                hidden_fixed += 1
            for l in must:
                lab[l][1] += 1
                if l not in miss:
                    lab[l][0] += 1
        if n % 300 == 0:
            print(f"{n}/{len(work)} {time.time()-t0:.0f}s", flush=True)
    by_kind = defaultdict(lambda: [0, 0, 0])
    for l, (m, t, nj) in lab.items():
        k = kinds[l]; by_kind[k][0] += m; by_kind[k][1] += t; by_kind[k][2] += nj
    worst = sorted(((l, m / t, nj, kinds[l]) for l, (m, t, nj) in lab.items() if t >= 15), key=lambda x: x[1])[:60]
    open_ids = {r for (r,) in open_jobs}
    open_stats = Counter()
    open_examples = defaultdict(list)
    for jid in open_ids:
        j = jobs.get(jid)
        if not j:
            continue
        must = list(search_dealbreaker_inputs(j).must_skills)
        ks = {label_kind(l) for l in must}
        open_stats["open_jobs"] += 1
        open_stats["with_gate"] += bool(must)
        for k in ks:
            open_stats[k] += 1
        for l in must:
            if label_kind(l) in ("taxonomy_role_category", "example_prose") and len(open_examples[label_kind(l)]) < 25:
                open_examples[label_kind(l)].append(l)
    out = {"jobs": len(work), "pairs": total,
           "sent_hidden_by_must_v8": round(hidden_any / total, 4),
           "sent_hidden_if_fixed_rule": round(hidden_fixed / total, 4),
           "hidden_involving_kind": {k: round(v / total, 4) for k, v in hidden_by_kind.items()},
           "coverage_by_kind": {k: {"coverage": round(m / t, 3), "label_uses": nj} for k, (m, t, nj) in by_kind.items()},
           "worst_labels": [(l, round(c, 3), nj, k) for l, c, nj, k in worst],
           "open_jobs": dict(open_stats), "open_examples": open_examples}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    json.dump(out, open("/research/out_gate_labels.json", "w"), ensure_ascii=False, indent=1)


asyncio.run(main())
