"""Study H: models pick the CORE of the client's must-have list; measure how many people the team
actually SENT pass a gate built from that core, vs how much of the base it hides.
No DB writes, no app telemetry: models called directly (keys from container env)."""
import ro_boot  # noqa: F401
import asyncio, json, math, os, random, re, statistics, time
from collections import defaultdict
import httpx
import data

ARGS = dict(a.split("=", 1) for a in os.environ.get("RESEARCH_ARGS", "").split() if "=" in a)
N = int(ARGS.get("n", 120)); SEED = int(ARGS.get("seed", 5))
MODELS = ARGS.get("models", "gpt-6-luna,claude-sonnet-5,claude-haiku-4-5-20251001,claude-opus-5-5").split(",")
PROMPT_VERSION = ARGS.get("prompt", "v1")

SYSTEM = {
"v1": """Jesteś Delivery Leadem w firmie body-leasingowej IT. Dostajesz zapytanie klienta o konsultanta: tytuł roli oraz listy MUST HAVE i NICE TO HAVE słowami klienta.
Zadanie: wskaż RDZEŃ zapytania — od 1 do 3 pozycji, bez których rekruter NIE wysłałby CV do klienta, bo kandydat bez nich po prostu nie wykona tej roli.
Zasady rdzenia:
- tylko konkretne technologie, języki programowania, frameworki, platformy, produkty lub narzędzia (np. Java, React, SAP FI, PEGA, Selenium, Azure, Terraform);
- bez wersji ("Java 8+" -> "Java"), bez umiejętności miękkich, języków obcych, branż, lat doświadczenia, metodyk (Agile/Scrum), ogólników (bazy danych, cloud, API);
- narzędzie podane jako przykład ("np.", "like", "lub podobne", "e.g.") nie jest rdzeniem;
- gdy klient dopuszcza alternatywy, zapisz jedną pozycję w formie "A lub B";
- wybieraj to, co definiuje rolę (Java developer -> Java; tester automatyzujący -> Selenium lub Playwright tylko jeśli klient wymaga konkretnego), a nie wszystko z listy;
- gdy rola nie ma technologicznego rdzenia (np. PM, analityk biznesowy, scrum master), zwróć pustą listę.
Pozostałe pozycje MUST przepisz do rest_must jako krótkie nazwy (bez wersji). Wyodrębnij też dziedzinę (branża/obszar biznesowy), wymagany język obcy z poziomem i minimalną liczbę lat, jeśli podane.
Odpowiedz wyłącznie JSON: {"core": [..], "rest_must": [..], "domain": [..], "language": "EN B2"|null, "min_years": liczba|null}""",
}


def user_msg(job, must_lines, nice_lines, stack):
    return (f"Tytuł: {job.title}\n\nMUST HAVE (słowa klienta):\n" + "\n".join(f"- {m}" for m in must_lines)
            + ("\n\nNICE TO HAVE:\n" + "\n".join(f"- {m}" for m in nice_lines) if nice_lines else "")
            + ("\n\nLista technologii z profilu (pomocniczo):\n" + ", ".join(stack) if stack else ""))


async def call(client, model, system, user):
    if model.startswith("gpt"):
        r = await client.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            json={"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                  "max_completion_tokens": 800, "reasoning_effort": "none", "store": False, "response_format": {"type": "json_object"}}, timeout=90)
        r.raise_for_status(); j = r.json()
        return j["choices"][0]["message"]["content"], j.get("usage", {})
    body = {"model": model, "max_tokens": 800, "system": system, "messages": [{"role": "user", "content": user}]}
    if "sonnet-5" in model:
        body["thinking"] = {"type": "disabled"}
    r = await client.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}, json=body, timeout=90)
    r.raise_for_status(); j = r.json()
    return "".join(b.get("text", "") for b in j["content"] if b.get("type") == "text"), j.get("usage", {})


def parse(txt):
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0)) if m else {}


def names(raw):
    out = []
    for x in raw or []:
        s = x.get("name") if isinstance(x, dict) else x
        if isinstance(s, str) and s.strip():
            out.append(s.strip())
    return out


async def main():
    await data.boot()
    from app.services.scoring_service import _champion_stack_must_names, canonical_skill_names, ALIAS_MAP, _alias_pattern
    cands = await data.load_candidates()
    pos = await data.load_positives()
    jobs = {j.id: j for j in await data.load_jobs()}
    known_pool = [c for c in cands.values() if c.known]
    random.seed(99); popsample = random.sample(known_pool, 1500)

    elig = []
    for jid, P in pos.items():
        j = jobs.get(jid)
        if not j or j.external_source == "manual":
            continue
        sent = [c for c, r in P.items() if r >= 1 and c in cands and cands[c].known]
        if len(sent) >= 3 and names(j.must_skills) and _champion_stack_must_names(j):
            elig.append(jid)
    if ARGS.get("only_file"):
        elig = [int(x) for x in json.load(open(ARGS["only_file"]))]
    random.seed(SEED); random.shuffle(elig); sample = sorted(elig[:N])
    print(f"eligible={len(elig)} sample={len(sample)} models={MODELS}", flush=True)
    if not ARGS.get("only_file"):
        json.dump(sample, open("/research/model_sample.json", "w"))

    def lab(x):
        return canonical_skill_names([x])[0] if canonical_skill_names([x]) else x.lower()

    def gate_eval(labels_by_job, need_fn=lambda L: len(L)):
        rec, srec, pr, nonempty = [], [], [], 0
        for jid in sample:
            L = [lab(x) for x in labels_by_job.get(jid) or []]
            P = pos[jid]
            sent = [cands[c] for c, r in P.items() if r >= 1 and c in cands and cands[c].known]
            strong = [c for c in sent if P[c.id] >= 2]
            def ok(c):
                if not L:
                    return True
                return sum(1 for l in L if data.present(l, c.canon, c.known)) >= need_fn(L)
            if L:
                nonempty += 1
            rec.append(sum(map(ok, sent)) / len(sent))
            if strong:
                srec.append(sum(map(ok, strong)) / len(strong))
            pr.append(sum(map(ok, popsample)) / len(popsample))
        r = statistics.mean(rec); p = statistics.mean(pr)
        return {"recall_sent": round(r, 3), "recall_strong": round(statistics.mean(srec), 3) if srec else None,
                "jobs_recall_lt50": round(sum(x < .5 for x in rec) / len(rec), 3), "base_pass": round(p, 4),
                "lift": round(r / p, 1), "jobs_with_gate": nonempty}

    # deterministic baselines
    pat = _alias_pattern()
    results = {}
    base = {}
    base["stack_all"] = {j: canonical_skill_names(_champion_stack_must_names(jobs[j])) for j in sample}
    base["stack_first1"] = {j: v[:1] for j, v in base["stack_all"].items()}
    base["stack_first2"] = {j: v[:2] for j, v in base["stack_all"].items()}
    def title_tech(j):
        found = []
        if pat is not None:
            for m in pat.finditer(jobs[j].title or ""):
                c = ALIAS_MAP.get(m.group(1).lower())
                if c and c not in found:
                    found.append(c)
        return found[:2]
    base["title_tech"] = {j: title_tech(j) for j in sample}
    for k, v in base.items():
        results[k] = gate_eval(v)
    results["stack_half"] = gate_eval(base["stack_all"], lambda L: max(1, math.ceil(len(L) / 2)))
    print(json.dumps(results, indent=1), flush=True)

    outputs = {}
    usage_tot = defaultdict(lambda: [0, 0])
    sem = asyncio.Semaphore(6)
    async with httpx.AsyncClient() as client:
        for model in MODELS:
            outs = {}
            async def one(jid):
                j = jobs[jid]
                u = user_msg(j, names(j.must_skills), names(j.nice_skills), _champion_stack_must_names(j))
                async with sem:
                    for attempt in range(3):
                        try:
                            txt, usage = await call(client, model, SYSTEM[PROMPT_VERSION], u)
                            usage_tot[model][0] += usage.get("input_tokens", usage.get("prompt_tokens", 0))
                            usage_tot[model][1] += usage.get("output_tokens", usage.get("completion_tokens", 0))
                            outs[jid] = parse(txt)
                            return
                        except Exception as e:
                            await asyncio.sleep(3 + attempt * 5)
                            last = type(e).__name__
                    outs[jid] = {"_error": last}
            t = time.time()
            await asyncio.gather(*(one(j) for j in sample))
            outputs[model] = outs
            errs = sum(1 for v in outs.values() if "_error" in v)
            core = {j: names(v.get("core")) for j, v in outs.items()}
            results[f"model:{model}"] = gate_eval(core) | {"errors": errs, "secs": round(time.time() - t),
                "avg_core": round(statistics.mean(len(v) for v in core.values()), 2), "tokens_in_out": usage_tot[model]}
            print(model, json.dumps(results[f"model:{model}"]), flush=True)
    TAG = ARGS.get("tag", PROMPT_VERSION)
    json.dump({"prompt": PROMPT_VERSION, "results": results}, open(f"/research/out_model_{TAG}.json", "w"), indent=1, ensure_ascii=False)
    json.dump({m: {str(j): v for j, v in o.items()} for m, o in outputs.items()}, open(f"/research/model_outputs_{TAG}.json", "w"), ensure_ascii=False)
    core_sets = defaultdict(dict)
    for m, o in outputs.items():
        for j, v in o.items():
            core_sets[str(j)][m.split("-")[1] if m.startswith("claude") else "luna"] = names(v.get("core"))
    json.dump(core_sets, open(f"/research/core_sets_{TAG}.json", "w"), ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())
