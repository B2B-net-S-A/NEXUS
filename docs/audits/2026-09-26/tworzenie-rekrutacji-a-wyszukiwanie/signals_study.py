"""Study E/F/G: do language, seniority and domain carry signal? Compare people the team SENT
vs the rest of the base (lift), and coverage of the data on both sides."""
import ro_boot  # noqa: F401
import asyncio, json, random, re, statistics
from collections import Counter
import data
from sqlalchemy import text


async def main():
    await data.boot()
    from app.core.database import AsyncSessionLocal
    from app.services import champion_view
    cands = await data.load_candidates()
    pos = await data.load_positives()
    jobs = {j.id: j for j in await data.load_jobs()}
    allc = list(cands.values())
    random.seed(3)
    out = {}

    # --- languages: candidate coverage & level coverage
    def langs(c):
        L = c.languages if isinstance(c.languages, list) else []
        return {(x.get("code") or "").upper(): (x.get("level") or "unknown") for x in L if isinstance(x, dict)}
    en_any = sum(1 for c in allc if "EN" in langs(c))
    en_level = sum(1 for c in allc if langs(c).get("EN", "unknown") not in ("unknown", "", None))
    out["lang_coverage"] = {"cands": len(allc), "has_EN": en_any, "EN_with_level": en_level,
                            "levels": Counter(langs(c).get("EN") for c in allc if "EN" in langs(c)).most_common(8)}
    # jobs demanding EN (champion language or must line mentioning english)
    EN_RX = re.compile(r"\b(english|angielsk|\bEN\b|B2|C1)", re.I)
    sent_en, sent_n = 0, 0
    for jid, P in pos.items():
        j = jobs.get(jid)
        if not j:
            continue
        txt = " ".join([str(champion_view.basics(j).get("language") or "")] + [str(x.get("name") if isinstance(x, dict) else x) for x in (j.must_skills or [])])
        if not EN_RX.search(txt):
            continue
        for c, r in P.items():
            if r >= 1 and c in cands:
                sent_n += 1; sent_en += "EN" in langs(cands[c])
    out["lang_sent_on_EN_jobs"] = {"sent": sent_n, "sent_with_EN_in_profile": sent_en,
                                   "base_share_EN": round(en_any / len(allc), 3)}

    # --- seniority: min years vs candidate years
    rows = []
    for jid, P in pos.items():
        j = jobs.get(jid)
        if not j:
            continue
        my = champion_view.basics(j).get("seniority_min_years")
        if not isinstance(my, (int, float)) or my <= 0:
            continue
        for c, r in P.items():
            if r >= 1 and c in cands:
                rows.append((my, cands[c].yoe, r))
    known = [(m, y) for m, y, _ in rows if y is not None]
    out["seniority"] = {"sent_pairs_with_job_min_years": len(rows), "with_cand_years": len(known),
        "meets_min": round(sum(y >= m for m, y in known) / max(1, len(known)), 3),
        "within_1y": round(sum(y >= m - 1 for m, y in known) / max(1, len(known)), 3),
        "base_years_known": round(sum(c.yoe is not None for c in allc) / len(allc), 3)}
    # base pass for typical min 5y
    base_known = [c.yoe for c in allc if c.yoe is not None]
    out["seniority"]["base_share_ge5y"] = round(sum(y >= 5 for y in base_known) / len(base_known), 3)

    # --- domain: champion domains/sectors vs CV text (SQL on keyword_fts, read-only)
    DOM = {"bank": r"bank|banking|bankow", "insurance": r"insurance|ubezpiecz", "telco": r"telco|telekom|telecom",
           "health": r"medyczn|health|zdrowi", "public": r"administracj|public sector|sektor publiczn|ministerst",
           "energy": r"energ|utilities", "ecommerce": r"e-?commerce|retail|handel"}
    async with AsyncSessionLocal() as db:
        rs = (await db.execute(text("SELECT id, lower(left(coalesce(raw_cv_text,''),20000)) AS txt FROM candidates WHERE coalesce(raw_cv_text,'')<>''"))).all()
    cvtxt = {r.id: r.txt for r in rs}
    base_ids = random.sample(list(cvtxt), 4000)
    dom_out = {}
    for d, rx in DOM.items():
        R = re.compile(rx)
        base_share = sum(1 for i in base_ids if R.search(cvtxt[i])) / len(base_ids)
        # jobs whose client/title/stack indicate this domain
        s_hit = s_n = 0
        for jid, P in pos.items():
            j = jobs.get(jid)
            if not j:
                continue
            cp = j.champion_profile if isinstance(j.champion_profile, dict) else {}
            proj = cp.get("project") if isinstance(cp.get("project"), dict) else {}
            blob = " ".join([j.title or "", str(proj.get("about") or ""), str(proj.get("responsibilities") or "")]).lower()
            if not R.search(blob):
                continue
            for c, r in P.items():
                if r >= 1 and c in cvtxt:
                    s_n += 1; s_hit += bool(R.search(cvtxt[c]))
        dom_out[d] = {"base_share": round(base_share, 3), "sent_on_domain_jobs": s_n,
                      "sent_share": round(s_hit / s_n, 3) if s_n else None,
                      "lift": round((s_hit / s_n) / base_share, 2) if s_n and base_share else None}
    out["domain"] = dom_out
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    json.dump(out, open("/research/out_signals.json", "w"), indent=1, ensure_ascii=False, default=str)


asyncio.run(main())
