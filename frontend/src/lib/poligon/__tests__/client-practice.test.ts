// Klient ćwiczebny Poligonu (22.11.2026): listy klientów, kontraktów, zamówień
// z maila i Finansów idą z zestawu, a kwoty widzi tylko rola, która widzi je
// na prawdziwym kliencie (jak `_redact_contract_finance` i profil klienta).

import { describe, expect, it } from "vitest";

import dataset from "../dataset.json";
import { NO_AMOUNTS, viewerFrom, withPracticeClient, type PoligonViewer } from "../amounts";
import { createPoligonStore, resolveDates, type PoligonDataset } from "../store";

const DATA = dataset as unknown as PoligonDataset;
const NOW = Date.UTC(2026, 10, 22, 12, 0, 0);
const CLIENT = DATA.meta.client_id;
const ACTIVE_CONTRACT = 990521;

const access = (granted: string[]) =>
  Object.fromEntries(
    ["delivery_view", "amounts_view", "company_results", "finance_module"].map((k) => [k, granted.includes(k) ? "manage" : "none"]),
  );
const DL = { role: "delivery_lead", effective_action_access: access(["delivery_view", "amounts_view"]) };
const TCM = { role: "talent_community_manager", effective_action_access: access(["delivery_view"]) };
const FINANCE = {
  role: "finance",
  analytics_capabilities: ["view_finance"],
  effective_action_access: access(["delivery_view", "amounts_view", "finance_module"]),
};

type Row = Record<string, unknown>;

function get(url: string, viewer: PoligonViewer, params?: Record<string, unknown>) {
  const store = createPoligonStore(DATA, NOW);
  const res = store.handle({ method: "get", url, params, viewer });
  if (res === "network") throw new Error(`${url} poszło do API`);
  return res;
}

describe("klient ćwiczebny: listy z zestawu, nie z API", () => {
  it.each([
    ["/api/clients/directory/clients", { state: "working", page: 1, page_size: 50 }],
    ["/api/contracts", { status: ["active", "ending"], group_by_candidate: true, page: 1 }],
    ["/api/order-mail/queue", { outcome: "needs_review", limit: 100 }],
    ["/api/finance/rate-divergences", undefined],
    ["/api/finance/order-cost-corrections", undefined],
  ])("%s pokazuje tylko klienta ćwiczebnego", (url, params) => {
    const res = get(url, viewerFrom(DL), params);
    expect(res.status).toBe(200);
    expect(JSON.stringify(res.data)).toContain("Bank Północny");
  });

  it("liczniki pigułek kontraktów mają własne odpowiedzi (nie pierwszą listę)", () => {
    const count = (params: Record<string, unknown>) =>
      (get("/api/contracts", viewerFrom(DL), { page: 1, page_size: 1, group_by_candidate: true, ...params }).data as { total: number }).total;
    expect(count({ status: ["draft", "ready_for_signature"] })).toBe(0);
    expect(count({ bucket: "order_after_end" })).toBe(1);
    expect(count({ bucket: "rate_document" })).toBe(1);
    expect(count({})).toBe(2);
  });

  it("karta klienta i kontrakt mają odpowiedzi pod identyfikatorami poligonu", () => {
    for (const url of [`/api/clients/${CLIENT}`, `/api/clients/${CLIENT}/profile`, `/api/contracts/${ACTIVE_CONTRACT}`, `/api/care/contracts/${ACTIVE_CONTRACT}/card`]) {
      expect(get(url, viewerFrom(DL)).status, url).toBe(200);
    }
  });
});

describe("klient ćwiczebny: kwoty tylko dla ról z kwotą", () => {
  it("Delivery Lead widzi stawki i marżę kontraktu", () => {
    const row = (get(`/api/contracts/${ACTIVE_CONTRACT}`, viewerFrom(DL)).data as Row);
    expect(row.rate_client).toBe(122);
    expect(row.margin).toBe(17);
  });

  it("TCM (podgląd Delivery bez „Stawki i kwoty”) nie dostaje żadnej kwoty", () => {
    const viewer = viewerFrom(TCM);
    expect(viewer.amounts).toBe(false);
    const row = get(`/api/contracts/${ACTIVE_CONTRACT}`, viewer).data as Row;
    for (const k of ["rate_client", "rate_candidate", "margin", "monthly_margin", "currency", "rate_unit", "rate_document_change"]) {
      expect(row[k], k).toBeNull();
    }
    expect(row.client_rate_schedule).toEqual([]);
    const profile = get(`/api/clients/${CLIENT}/profile`, viewer).data as { summary: Row; active_consultants: Row[] };
    expect(profile.summary.active_mrr).toBeNull();
    expect(profile.active_consultants[0].monthly_rate_client).toBeNull();
    const directory = get("/api/clients/directory/clients", viewer, { state: "working" }).data as { amounts_visible: boolean; items: Row[] };
    expect(directory.amounts_visible).toBe(false);
    expect(directory.items[0].monthly_margin).toBeNull();
    const docs = get(`/api/contracts/${ACTIVE_CONTRACT}/rate-documents`, viewer).data as { amounts_visible: boolean; items: Array<{ quote: unknown }> };
    expect(docs.amounts_visible).toBe(false);
    expect(docs.items[0].quote).toBeNull();
  });

  it("nieznana osoba = bez kwot (bezpieczniej zdjąć niż pokazać)", () => {
    expect(viewerFrom(null)).toEqual(NO_AMOUNTS);
    const row = get(`/api/contracts/${ACTIVE_CONTRACT}`, NO_AMOUNTS).data as Row;
    expect(row.rate_client).toBeNull();
  });

  it("Finanse bez „Wyników firmy” widzą stawki, ale nie marżę w wierszach listy kontraktów", () => {
    const viewer = viewerFrom(FINANCE);
    expect(viewer).toEqual({ amounts: true, companyMargin: false });
    const list = get("/api/contracts", viewer, { status: ["active", "ending"], group_by_candidate: true, page: 1 }).data as { items: Row[] };
    expect(list.items[0].rate_client).toBe(122);
    expect(list.items[0].margin).toBeNull();
    // Szczegóły kontraktu: marża zostaje (serwer ukrywa ją tylko na liście).
    expect((get(`/api/contracts/${ACTIVE_CONTRACT}`, viewer).data as Row).margin).toBe(17);
  });

  it("odpowiedzi rekrutacji ćwiczebnej (nagranie) nie tracą stawek kandydata", () => {
    const board = get(`/api/pipeline/kanban/${DATA.meta.job_id}`, NO_AMOUNTS).data;
    expect(JSON.stringify(board)).toBe(JSON.stringify(resolveDates(DATA.responses[`GET /api/pipeline/kanban/${DATA.meta.job_id}`], NOW)));
  });
});

describe("klient ćwiczebny w portfelu ćwiczącego Delivery Leada", () => {
  const me = {
    ...DL,
    data_scope: { kind: "delivery_clients", allowed_client_ids: [11, 16], finance_client_ids: [11] },
  };

  it("dopisuje klienta ćwiczebnego do przypisań i kwot DL-a", () => {
    const out = withPracticeClient(me, CLIENT) as typeof me;
    expect(out.data_scope.allowed_client_ids).toEqual([11, 16, CLIENT]);
    expect(out.data_scope.finance_client_ids).toEqual([11, CLIENT]);
  });

  it("bez „Stawki i kwoty: podgląd” klient trafia tylko do przypisań", () => {
    const out = withPracticeClient({ ...me, effective_action_access: access(["delivery_view"]) }, CLIENT) as typeof me;
    expect(out.data_scope.finance_client_ids).toEqual([11]);
    expect(out.data_scope.allowed_client_ids).toContain(CLIENT);
  });

  it("konto spoza portfela DL (admin, Finanse) zostaje bez zmian", () => {
    const admin = { role: "admin", data_scope: { kind: "all" } };
    expect(withPracticeClient(admin, CLIENT)).toBe(admin);
  });
});

describe("daty względne miesiąca", () => {
  it("@relm:-1 to poprzedni miesiąc (rozliczenie klienta)", () => {
    expect(resolveDates("@relm:-1", NOW)).toBe("2026-10");
    expect(resolveDates("@relm:0", Date.UTC(2026, 0, 15))).toBe("2026-01");
    expect(resolveDates("@relm:-1", Date.UTC(2026, 0, 15))).toBe("2025-12");
  });
});
