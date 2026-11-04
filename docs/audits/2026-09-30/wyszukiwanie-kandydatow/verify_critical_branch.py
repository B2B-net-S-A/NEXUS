"""Weryfikacja kodu gałęzi (30.09.2026): statystyki krytycznych liczone
`critical_skills.compute_stats` na produkcji (czas!), potem odsetek osób
wysłanych do klienta, które bramka v9 ukryłaby (podpowiedź z historii,
bez decyzji DL — tak działa każda rekrutacja historyczna). Uwaga: statystyki
obejmują też daną rekrutację (brak leave-one-out) — liczba lekko optymistyczna.
Tylko odczyt."""
import ro_boot  # noqa: F401
import asyncio, json, statistics, time
from collections import defaultdict


async def main():
    from sqlalchemy import select, text
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.services import critical_skills
    from app.services.dealbreaker_filters import missing_must_skills, dealbreaker_inputs_for_job
    from app.services.must_text_evidence import EVIDENCE_NOTE_TYPES, MustTextEvidence, text_met_labels, has_any_data
    from app.services.must_gate_terms import gate_requirement
    from app.services.scoring_service import job_explicit_must_skills
    from app.services.skill_taxonomy_loader import refresh_alias_map

    await refresh_alias_map()
    t0 = time.time()
    async with AsyncSessionLocal() as db:
        payload = await critical_skills.compute_stats(db)
    secs = round(time.time() - t0, 1)
    critical_skills.set_payload(payload)
    print(f"compute_stats: {secs}s labels={len(payload['labels'])} jobs={payload['jobs']}", flush=True)

    hid = tot = jobs_with = labels_n = 0
    losing = 0; per_job = 0; no_data = 0
    source = defaultdict(int)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT job_id, array_agg(DISTINCT candidate_id) FROM analytics_first_milestones "
            "WHERE job_id IS NOT NULL AND stage::text = ANY(:s) GROUP BY job_id "
            "HAVING count(DISTINCT candidate_id) >= 3"),
            {"s": ["cv_sent", "interview", "client_interview", "acceptance", "hired"]})).all()
        sent_by_job = {int(j): list(c) for j, c in rows}
        ids = sorted(sent_by_job)
        for start in range(0, len(ids), 50):
            chunk = ids[start:start + 50]
            jobs = (await db.execute(select(Job).where(Job.id.in_(chunk)))).scalars().all()
            work = []
            for job in jobs:
                must = [m for m in job_explicit_must_skills(job) if gate_requirement(m)]
                if not must:
                    continue
                inputs = dealbreaker_inputs_for_job(job)
                work.append((job, must, list(inputs.must_skills), inputs.critical_source))
            need = sorted({c for j, *_ in work for c in sent_by_job[j.id]})
            cands = {c.id: c for c in (await db.execute(select(Candidate).where(Candidate.id.in_(need)))).scalars()}
            notes = defaultdict(list)
            for cid, at, content in (await db.execute(text(
                    "SELECT candidate_id, created_at, content FROM notes WHERE candidate_id = ANY(:ids) "
                    "AND source_deleted_at IS NULL AND note_type::text = ANY(:t)"),
                    {"ids": need, "t": list(EVIDENCE_NOTE_TYPES)})).all():
                notes[cid].append((at, content or ""))
            for job, must, crit, src in work:
                per_job += 1
                source[src] += 1
                jobs_with += bool(crit)
                labels_n += len(crit)
                cutoff = job.opened_at or job.created_at
                h = n = 0
                for cid in sent_by_job[job.id]:
                    c = cands.get(cid)
                    if c is None:
                        continue
                    nts = [t for at, t in notes.get(cid, ()) if cutoff is None or at < cutoff]
                    c._must_text_evidence = MustTextEvidence(key=tuple(must), met=text_met_labels(c, must, nts), has_notes=bool(nts))
                    n += 1
                    if not has_any_data(c, c._must_text_evidence):
                        no_data += 1
                    if crit and set(missing_must_skills(c, crit)):
                        h += 1
                hid += h; tot += n
                losing += (n and h / n > 0.5)
            db.expunge_all()
    out = {"compute_stats_seconds": secs, "stats_labels": len(payload["labels"]), "stats_jobs": payload["jobs"],
           "jobs": per_job, "sent_pairs": tot, "sent_hidden_by_critical": round(hid / max(1, tot), 4),
           "jobs_losing_gt50pct": round(losing / max(1, per_job), 4),
           "jobs_with_critical": round(jobs_with / max(1, per_job), 4),
           "avg_critical_labels": round(labels_n / max(1, per_job), 3),
           "sent_without_any_data": round(no_data / max(1, tot), 4),
           "critical_source": dict(source),
           "top_stats": sorted(((k, v["rate"], v["jobs"]) for k, v in payload["labels"].items() if v["jobs"] >= 5),
                               key=lambda x: -x[2])[:40]}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    json.dump(out, open("/research/out_verify_critical.json", "w"), ensure_ascii=False, indent=1)
    json.dump(payload, open("/research/critical_stats_payload.json", "w"), ensure_ascii=False)


asyncio.run(main())
