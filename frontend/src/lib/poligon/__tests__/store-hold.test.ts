import { describe, expect, it } from "vitest";

import dataset from "../dataset.json";
import { createPoligonStore, type PoligonDataset } from "../store";

const DATA = dataset as unknown as PoligonDataset;
const NOW = Date.UTC(2026, 10, 26, 10, 0, 0);
const JOB = DATA.meta.job_id;

type Res = { status: number; data: Record<string, unknown> };

/**
 * Lekcje „Wstrzymana rekrutacja” (26.11.2026): rekruter zgłasza DL-owi, DL
 * wstrzymuje. Odczyt na Poligonie jest bez stanu, bo etap „sam” po pokazie
 * znowu potrzebuje „Wstrzymaj rekrutację…” i „Zgłoś DL-owi”.
 */
describe("poligon: wstrzymanie rekrutacji ćwiczebnej", () => {
  const call = (method: string, url: string, canManageHold: boolean, body?: unknown) =>
    createPoligonStore(DATA, NOW).handle({ method, url, body, canManageHold }) as Res;

  it("odczyt: „Szukamy”, a zarządzać może tylko DL, HoR i admin", () => {
    const rec = call("get", `/api/jobs/${JOB}/hold`, false);
    expect(rec.status).toBe(200);
    expect(rec.data).toMatchObject({ job_id: JOB, state: "searching", can_manage: false, my_open_report: null });
    expect(rec.data.recipients).toEqual([]);
    const dl = call("get", `/api/jobs/${JOB}/hold`, true);
    expect(dl.data.can_manage).toBe(true);
    expect((dl.data.recipients as unknown[]).length).toBe(1);
  });

  it("rekruter zgłasza (201), ale nie wstrzymuje (403)", () => {
    expect(call("post", `/api/jobs/${JOB}/hold/report`, false, { note: "Klient stoi" }).status).toBe(201);
    expect(call("put", `/api/jobs/${JOB}/hold`, false, { reason: "x" }).status).toBe(403);
  });

  it("DL wstrzymuje — odpowiedź jak z serwera, a odczyt potem znowu „Szukamy”", () => {
    const store = createPoligonStore(DATA, NOW);
    const put = store.handle({
      method: "put",
      url: `/api/jobs/${JOB}/hold`,
      body: { reason: "Klient wstrzymał budżet", review_on: "2026-12-10", notify: true },
      canManageHold: true,
    }) as Res;
    expect(put.status).toBe(200);
    expect(put.data).toMatchObject({ state: "on_hold", reason: "Klient wstrzymał budżet", review_on: "2026-12-10", by_name: "Ty" });
    const after = store.handle({ method: "get", url: `/api/jobs/${JOB}/hold`, canManageHold: true }) as Res;
    expect(after.data.state).toBe("searching");
  });

  it("inna rekrutacja nie idzie przez ćwiczebną obsługę", () => {
    const other = createPoligonStore(DATA, NOW).handle({ method: "put", url: "/api/jobs/1/hold", body: {}, canManageHold: true });
    expect(other).not.toMatchObject({ status: 200 });
  });
});
