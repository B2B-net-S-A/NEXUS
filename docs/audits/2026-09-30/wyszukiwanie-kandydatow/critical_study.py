"""Badanie 30.09.2026: „umiejętności krytyczne” zamiast bramki na WSZYSTKICH must.

Symulacja listy, którą widzi rekruter (pełny przegląd bazy / propozycje), na tle
losowych kandydatów, z PRODUKCYJNĄ oceną (`canonical_fit`) i PRODUKCYJNĄ regułą
dowodu must (v8: lista umiejętności, profil, CV, notatki-rozmowy). Notatki liczone
TYLKO sprzed otwarcia rekrutacji (inaczej notatka z tego samego procesu zawyża
wynik osób wysłanych). Warianty bramki różnią się wyłącznie ZBIOREM must, który
ukrywa; reszta bramek (budżet, biuro, tylko etat) identyczna jak na produkcji.

RESEARCH_ARGS: n=200 seed=7 since=2024-07-01 pool=3000 luna=1
Wyjście: /research/out_critical.json (+ /research/critical_luna.json — wybory modelu).
"""
import ro_boot  # noqa: F401
import asyncio, json, math, os, random, statistics, time
from collections import Counter, defaultdict
from dataclasses import replace

import data

ARGS = dict(a.split("=", 1) for a in os.environ.get("RESEARCH_ARGS", "").split() if "=" in a)
N = int(ARGS.get("n", 200)); SEED = int(ARGS.get("seed", 7))
SINCE = ARGS.get("since", "2024-07-01"); POOL = int(ARGS.get("pool", 3000))
USE_LUNA = ARGS.get("luna", "1") == "1"

LUNA_SYSTEM = """Jesteś Delivery Leadem w firmie body-leasingowej IT. Zakładasz rekrutację i zaznaczasz w profilu Championa umiejętności KRYTYCZNE.
Umiejętność krytyczna = kandydat, który jej nie ma (nie ma jej w CV, profilu ani w notatkach z rozmów), NA PEWNO nie zostanie wysłany do klienta — system go ukryje.
Pozostałe must have zostają jako wymagania, które tylko podnoszą pozycję kandydata na liście.
Zasady:
- wybieraj WYŁĄCZNIE z podanej listy MUST HAVE, przepisując pozycję dokładnie tak, jak jest zapisana;
- zwykle 1 pozycja, najwyżej 3; to technologia, która definiuje rolę (Java developer -> Java; SAP FI konsultant -> SAP FI);
- nie wybieraj narzędzi pomocniczych, przykładów, metodyk, ogólników ani rzeczy, których brak można nadrobić;
- jeśli żadna pozycja nie jest bezwzględnie konieczna, zwróć pustą listę.
Odpowiedz wyłącznie JSON: {"critical": [..]}"""


def metrics(ranked, rel, strong):
    n = len(rel)
    out = {
        "R@20": len([c for c in ranked[:20] if c in rel]) / min(n, 20),
        "R@100": len([c for c in ranked[:100] if c in rel]) / min(n, 100),
        "P@10": len([c for c in ranked[:10] if c in rel]) / 10,
        "MRR": next((1 / (i + 1) for i, c in enumerate(ranked) if c in rel), 0.0),
        "visible_pos": len(set(ranked) & rel) / n,
    }
    if strong:
        out["visible_strong"] = len(set(ranked) & strong) / len(strong)
        out["R@100_strong"] = len([c for c in ranked[:100] if c in strong]) / min(len(strong), 100)
    return out


async def luna_critical(jobs_by_id, sample, must_of):
    path = "/research/critical_luna.json"
    cache = json.load(open(path)) if os.path.exists(path) else {}
    import httpx
    todo = [j for j in sample if str(j) not in cache and must_of[j]]
    sem = asyncio.Semaphore(6)
    usage = [0, 0]
    async with httpx.AsyncClient() as client:
        async def one(jid):
            j = jobs_by_id[jid]
            from app.services import champion_view
            nice = []
            try:
                from app.services.scoring_service import job_skill_requirements
                nice = job_skill_requirements(j).get("nice", [])
            except Exception:
                pass
            desc = (j.description or "")[:1500]
            user = (f"Tytuł: {j.working_title or j.title}\n\nMUST HAVE:\n" + "\n".join(f"- {m}" for m in must_of[jid])
                    + ("\n\nNICE TO HAVE:\n" + "\n".join(f"- {m}" for m in nice[:15]) if nice else "")
                    + (f"\n\nOpis:\n{desc}" if desc.strip() else ""))
            async with sem:
                for attempt in range(3):
                    try:
                        r = await client.post("https://api.openai.com/v1/chat/completions",
                            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                            json={"model": "gpt-6-luna", "messages": [{"role": "system", "content": LUNA_SYSTEM}, {"role": "user", "content": user}],
                                  "max_completion_tokens": 300, "reasoning_effort": "none", "store": False,
                                  "response_format": {"type": "json_object"}}, timeout=90)
                        r.raise_for_status(); body = r.json()
                        u = body.get("usage", {}); usage[0] += u.get("prompt_tokens", 0); usage[1] += u.get("completion_tokens", 0)
                        got = json.loads(body["choices"][0]["message"]["content"]).get("critical") or []
                        allowed = {m.lower(): m for m in must_of[jid]}
                        cache[str(jid)] = [allowed[x.lower()] for x in got if isinstance(x, str) and x.lower() in allowed][:3]
                        return
                    except Exception as e:  # noqa: BLE001
                        last = type(e).__name__
                        await asyncio.sleep(3 + 5 * attempt)
                cache[str(jid)] = {"_error": last}
        await asyncio.gather(*(one(j) for j in todo))
    json.dump(cache, open(path, "w"), ensure_ascii=False)
    print("luna tokens in/out", usage, flush=True)
    return {int(k): v for k, v in cache.items() if isinstance(v, list)}


async def main():
    await data.boot()
    import datetime
    from sqlalchemy import select, text
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.services.canonical_fit import score_candidates
    from app.services.request_matching_context import build_request_context
    from app.services.requirement_contract import search_dealbreaker_inputs, requirements_for_job
    from app.services.dealbreaker_filters import apply_dealbreakers, missing_must_skills
    from app.services.must_text_evidence import MustTextEvidence, text_met_labels, mentions, has_any_data
    from app.services.must_gate_terms import gate_requirement
    from app.services.scoring_service import candidate_skill_names, skill_present, job_skill_requirements
    from scripts.eval_matching import DEFAULT_PROFILE, _to_scoring_profile

    pos = await data.load_positives()
    jobs = {j.id: j for j in await data.load_jobs()}
    since = datetime.date.fromisoformat(SINCE)

    def opened(j):
        d = j.opened_at or j.created_at
        return d.date() if hasattr(d, "date") else d

    must_of, elig = {}, []
    for jid, P in pos.items():
        j = jobs.get(jid)
        if not j or j.external_source == "manual":
            continue
        sent = [c for c, r in P.items() if r >= 1]
        if len(sent) < 3 or opened(j) is None or opened(j) < since:
            continue
        must = list(search_dealbreaker_inputs(j).must_skills)
        if not must:
            continue
        must_of[jid] = must
        elig.append(jid)
    random.seed(SEED); random.shuffle(elig); sample = sorted(elig[:N])
    print(f"eligible={len(elig)} sample={len(sample)}", flush=True)

    luna = await luna_critical(jobs, sample, must_of) if USE_LUNA else {}

    async with AsyncSessionLocal() as db:
        all_ids = [r for (r,) in (await db.execute(select(Candidate.id))).all()]
        base_n = len(all_ids)
        random.seed(1234); rnd = set(random.sample(all_ids, POOL))
        need = set(rnd)
        for jid in sample:
            need.update(c for c, r in pos[jid].items() if r >= 1)
        cobj = {}
        ids = sorted(need)
        for i in range(0, len(ids), 1000):
            for c in (await db.execute(select(Candidate).where(Candidate.id.in_(ids[i:i + 1000])))).scalars().all():
                db.expunge(c); cobj[c.id] = c
        notes = defaultdict(list)  # cid -> [(created_at, content)]
        for i in range(0, len(ids), 2000):
            for cid, at, content in (await db.execute(text(
                "SELECT candidate_id, created_at, content FROM notes WHERE candidate_id = ANY(:ids) "
                "AND source_deleted_at IS NULL AND note_type::text = ANY(:t)"),
                {"ids": ids[i:i + 2000], "t": ["call", "meeting", "general", "interview"]})).all():
                notes[cid].append((at, content or ""))
    print(f"loaded {len(cobj)} candidates, notes for {len(notes)}; base={base_n}", flush=True)
    rnd = rnd & set(cobj)
    scale = base_n / len(rnd)

    # przebieg 1: kto z wysłanych ma które must (do reguły historycznej i wyroczni)
    label_hits = defaultdict(lambda: [0, 0])  # canonical label -> [met, total] per job-list
    per_job_hits = {}
    agg = defaultdict(lambda: defaultdict(list))
    src_counter = Counter()
    t0 = time.time()
    rows_for_hist = {}
    profile = _to_scoring_profile(DEFAULT_PROFILE)

    for n, jid in enumerate(sample):
        j = jobs[jid]
        rel = {c for c, r in pos[jid].items() if r >= 1 and c in cobj}
        strong = {c for c, r in pos[jid].items() if r >= 2 and c in cobj}
        if len(rel) < 3:
            continue
        pool = [cobj[c] for c in rnd | rel]
        must = must_of[jid]
        cutoff = j.opened_at or j.created_at
        inputs = search_dealbreaker_inputs(j)
        # dowód v8 z notatkami tylko sprzed otwarcia rekrutacji
        missing, missing_nonotes, missing_list = {}, {}, {}
        for c in pool:
            nts = [t for (at, t) in notes.get(c.id, ()) if cutoff is None or at < cutoff]
            met = text_met_labels(c, must, nts)
            c._must_text_evidence = MustTextEvidence(key=tuple(must), met=met, has_notes=bool(nts))
            mm = set(missing_must_skills(c, must))
            missing[c.id] = mm
            # warianty dowodu (tylko do opisu źródeł)
            skills = candidate_skill_names(c)
            listed = {l for l in must if skill_present(l, skills) or any(skill_present(o, skills) for o in (gate_requirement(l).options if gate_requirement(l) else (l,)))}
            missing_list[c.id] = set(must) - listed
            nonotes = text_met_labels(c, must)
            missing_nonotes[c.id] = set(must) - listed - set(nonotes)
            if c.id in rel:
                for l in must:
                    if l in listed:
                        src_counter["list"] += 1
                    elif l in nonotes:
                        src_counter["profile_or_cv"] += 1
                    elif l not in mm:
                        src_counter["notes_before"] += 1
                    else:
                        src_counter["missing"] += 1
        base_vis = {c.id for c in apply_dealbreakers(pool, inputs=replace(inputs, must_skills=())).kept}
        ctx = build_request_context(j, profile)
        fits = await score_candidates(None, ctx, pool)
        fit = {f.breakdown.candidate_id: (f.fit_score if f.fit_score is not None else -1.0) for f in fits}
        # nice (dowód: lista + profil/CV; notatki sprzed otwarcia)
        reqs = job_skill_requirements(j)
        nice = [l for l in reqs.get("nice", []) if gate_requirement(l)]
        nice_met = {}
        for c in pool:
            if not nice:
                nice_met[c.id] = 0.0; continue
            nts = [t for (at, t) in notes.get(c.id, ()) if cutoff is None or at < cutoff]
            skills = candidate_skill_names(c)
            tm = text_met_labels(c, nice, nts)
            nice_met[c.id] = sum(1 for l in nice if l in tm or skill_present(l, skills)) / len(nice)
        must_frac = {cid: 1 - len(missing[cid]) / len(must) for cid in missing}
        # pozycje wysłanych do reguły historycznej
        cov = {l: sum(1 for c in rel if l not in missing[c]) / len(rel) for l in must}
        rows_for_hist[jid] = cov
        per_job_hits[jid] = {"rel": rel, "strong": strong, "fit": fit, "base_vis": base_vis, "missing": missing,
                             "missing_nonotes": missing_nonotes, "missing_list": missing_list,
                             "must": must, "must_frac": must_frac, "nice_met": nice_met, "nice_n": len(nice),
                             "title": (j.working_title or j.title or "")}
        if n % 10 == 0:
            print(f"{n}/{len(sample)} {time.time()-t0:.0f}s", flush=True)

    # reguła historyczna: odsetek wysłanych, którzy mają daną technologię (bez tej rekrutacji)
    label_sum = defaultdict(lambda: [0.0, 0])
    for jid, cov in rows_for_hist.items():
        for l, v in cov.items():
            label_sum[l.lower()][0] += v; label_sum[l.lower()][1] += 1

    def hist_rate(l, jid):
        s, k = label_sum[l.lower()]
        own = rows_for_hist[jid].get(l)
        if own is not None:
            s -= own; k -= 1
        return (s / k) if k >= 3 else None

    for jid, d in per_job_hits.items():
        must, rel, strong, fit = d["must"], d["rel"], d["strong"], d["fit"]
        title_low = d["title"]
        def vis(S, miss=d["missing"]):
            S = set(S)
            return [c for c in sorted(d["base_vis"], key=lambda c: (-fit.get(c, -1), c)) if not (miss[c] & S)]
        P = {}
        P["none"] = []
        P["all_v8"] = must
        P["first1"] = must[:1]
        P["first2"] = must[:2]
        P["title"] = [l for l in must if gate_requirement(l) and mentions(gate_requirement(l), title_low)][:2]
        P["luna"] = luna.get(jid, []) if USE_LUNA else []
        P["hist90"] = [l for l in must if (hist_rate(l, jid) or 0) >= 0.9]
        P["hist80"] = [l for l in must if (hist_rate(l, jid) or 0) >= 0.8]
        cov = rows_for_hist[jid]
        best = sorted(must, key=lambda l: -cov[l])
        P["oracle1"] = best[:1]
        P["oracle2"] = best[:2]
        lists = {}
        for name, S in P.items():
            lists[name] = vis(S)
        # dowód słabszy (tylko lista umiejętności) — tak działała bramka do 27.09
        lists["all_listonly_v7ish"] = vis(must, d["missing_list"])
        lists["all_no_notes"] = vis(must, d["missing_nonotes"])
        # punkty za must / nice (bez bramki must i z bramką luna)
        for base_name in ("none", "luna", "title"):
            for wm, wn in ((10, 0), (20, 0), (0, 10), (10, 5), (20, 10)):
                sc = {c: fit.get(c, -1) + wm * d["must_frac"][c] + wn * d["nice_met"][c] for c in lists[base_name]}
                lists[f"{base_name}+m{wm}n{wn}"] = sorted(lists[base_name], key=lambda c: (-sc[c], c))
        for name, ranked in lists.items():
            m = metrics(ranked, rel, strong)
            rv = [c for c in ranked if c in rnd]
            m["visible_base"] = len(rv) / len(rnd)
            # ≥ próg propozycji nocnych (70) i wśród „pierwszych 60” po przeskalowaniu na pełną bazę
            ge = [c for c in ranked if fit.get(c, -1) >= 70]
            m["props_ge70_est"] = len([c for c in ge if c in rnd]) * scale
            ranks_rel = [sum(1 for x in ranked[:i] if x in rnd) * scale for i, c in enumerate(ranked) if c in rel]
            m["pos_in_top60_est"] = sum(1 for r in ranks_rel if r < 60) / len(rel)
            m["pos_in_top300_est"] = sum(1 for r in ranks_rel if r < 300) / len(rel)
            m["crit_n"] = len(P.get(name, [])) if name in P else None
            m["empty_list"] = 1.0 if not rv else 0.0
            for k, x in m.items():
                if x is not None:
                    agg[name][k].append(x)
    summary = {v: {k: round(statistics.mean(x), 4) for k, x in dd.items()} | {"jobs": len(dd["R@20"])} for v, dd in agg.items()}
    tot = sum(src_counter.values())
    out = {"sample": len(per_job_hits), "base": base_n, "pool_random": len(rnd),
           "evidence_sources_for_sent": {k: round(v / tot, 4) for k, v in src_counter.items()},
           "must_len": statistics.mean(len(d["must"]) for d in per_job_hits.values()),
           "luna_avg_critical": statistics.mean(len(v) for k, v in luna.items() if k in per_job_hits) if luna else None,
           "hist_labels": {l: round(s / k, 3) for l, (s, k) in sorted(label_sum.items(), key=lambda x: -x[1][1])[:60]},
           "summary": summary}
    print(json.dumps(out, indent=1, ensure_ascii=False))
    json.dump(out, open("/research/out_critical.json", "w"), indent=1, ensure_ascii=False)
    json.dump({str(j): {"must": d["must"], "luna": luna.get(j), "cov": rows_for_hist[j]} for j, d in per_job_hits.items()},
              open("/research/critical_per_job.json", "w"), ensure_ascii=False, indent=0)


if __name__ == "__main__":
    asyncio.run(main())
