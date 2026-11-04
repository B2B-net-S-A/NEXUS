import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NewJobLeadRow } from "@/lib/api/boardTasks";
import {
  EMPTY_LEAD_FILTERS,
  filterLeads,
  hasLeadFilters,
  leadFilterOptions,
  liveLeadFilters,
  readStoredLeadFilters,
  writeStoredLeadFilters,
  type LeadFilters,
} from "@/lib/new-job-leads-filters";

function lead(over: Partial<NewJobLeadRow> = {}): NewJobLeadRow {
  return {
    job_id: 11,
    title: "Full Stack Java Developer",
    client_name: "Bank Północny",
    category_id: 2,
    category_name: "Development",
    category_slug: "software_development",
    participants: 5,
    priority_level: "p2",
    delivery_lead_name: "Anna Lis",
    handed_off_at: "2026-10-02T08:42:00Z",
    lead_user_id: 7,
    lead_name: "Marek Dąb",
    lead_role: "recruiter",
    lead_source: "auto",
    assigned_by_name: null,
    proposed: false,
    pending_reason: null,
    ...over,
  };
}

const ROWS: NewJobLeadRow[] = [
  lead({ job_id: 1 }),
  lead({ job_id: 2, client_name: "Żabka Fikcyjna", priority_level: "p1" }),
  lead({
    job_id: 3,
    client_name: "Ubezpieczenia Wzorcowe",
    category_id: 4,
    category_name: "QA",
    category_slug: "security_quality",
    delivery_lead_name: "Piotr Zieliński",
    lead_user_id: 9,
    lead_name: "Ewa Buk",
  }),
  lead({
    job_id: 4,
    category_id: null,
    category_name: null,
    category_slug: null,
    delivery_lead_name: null,
    lead_user_id: null,
    lead_name: null,
    pending_reason: "none",
  }),
];

const only = (over: Partial<LeadFilters>): LeadFilters => ({ ...EMPTY_LEAD_FILTERS, ...over });
const ids = (rows: NewJobLeadRow[]) => rows.map((row) => row.job_id);

describe("leadFilterOptions — opcje z samych wierszy", () => {
  const options = leadFilterOptions(ROWS);

  it("klienci po polsku alfabetycznie, bez powtórzeń", () => {
    expect(options.client.map((o) => o.label)).toEqual([
      "Bank Północny",
      "Ubezpieczenia Wzorcowe",
      "Żabka Fikcyjna",
    ]);
  });

  it("„bez …” stoi na końcu i tylko wtedy, gdy taki wiersz jest", () => {
    expect(options.cat.map((o) => o.label)).toEqual(["Development", "QA", "Bez kategorii"]);
    expect(options.dl.at(-1)).toEqual({ value: "none", label: "Bez Delivery Leada" });
    expect(options.who.at(-1)).toEqual({ value: "none", label: "Bez prowadzącego" });
    const full = leadFilterOptions(ROWS.slice(0, 3));
    expect(full.cat.some((o) => o.value === "none")).toBe(false);
    expect(full.who.some((o) => o.value === "none")).toBe(false);
  });

  it("priorytety w kolejności poziomów, tylko te z listy", () => {
    expect(options.prio.map((o) => o.value)).toEqual(["p1", "p2"]);
  });

  it("kategoria może dostać krótką nazwę z plakietki", () => {
    const short = leadFilterOptions(ROWS, (row) => (row.category_id === 2 ? "Dev" : row.category_name));
    expect(short.cat.map((o) => o.label)).toEqual(["Dev", "QA", "Bez kategorii"]);
  });
});

describe("filterLeads", () => {
  it("bez filtrów oddaje wszystko w kolejności z serwera", () => {
    expect(ids(filterLeads(ROWS, EMPTY_LEAD_FILTERS))).toEqual([1, 2, 3, 4]);
    expect(hasLeadFilters(EMPTY_LEAD_FILTERS)).toBe(false);
  });

  it.each<[string, Partial<LeadFilters>, number[]]>([
    ["klient", { client: "Bank Północny" }, [1, 4]],
    ["kategoria", { cat: "4" }, [3]],
    ["bez kategorii", { cat: "none" }, [4]],
    ["Delivery Lead", { dl: "Anna Lis" }, [1, 2]],
    ["bez Delivery Leada", { dl: "none" }, [4]],
    ["prowadzący", { who: "7" }, [1, 2]],
    ["bez prowadzącego", { who: "none" }, [4]],
    ["priorytet", { prio: "p1" }, [2]],
  ])("%s", (_name, filters, expected) => {
    expect(ids(filterLeads(ROWS, only(filters)))).toEqual(expected);
  });

  it("filtry łączą się przez „i”", () => {
    expect(ids(filterLeads(ROWS, only({ client: "Bank Północny", who: "7" })))).toEqual([1]);
    expect(ids(filterLeads(ROWS, only({ cat: "4", prio: "p1" })))).toEqual([]);
  });
});

describe("liveLeadFilters — wybór, którego nie ma już na liście, przestaje filtrować", () => {
  it("zostawia wybory obecne w opcjach", () => {
    const chosen = only({ client: "Żabka Fikcyjna", prio: "p1" });
    expect(liveLeadFilters(chosen, leadFilterOptions(ROWS))).toEqual(chosen);
  });

  it("zdejmuje klienta, którego ostatnia rekrutacja zeszła z listy", () => {
    const chosen = only({ client: "Żabka Fikcyjna", who: "7" });
    const left = ROWS.filter((row) => row.job_id !== 2);
    expect(liveLeadFilters(chosen, leadFilterOptions(left))).toEqual(only({ who: "7" }));
  });
});

describe("pamięć wyboru — osobno dla konta", () => {
  beforeEach(() => window.localStorage.clear());

  it("zapisany wybór wraca dla tego samego konta, inne konto zaczyna bez filtrów", () => {
    const chosen = only({ client: "Bank Północny", cat: "none", prio: "p1" });
    writeStoredLeadFilters(7, chosen);
    expect(readStoredLeadFilters(7)).toEqual(chosen);
    expect(readStoredLeadFilters(8)).toEqual(EMPTY_LEAD_FILTERS);
  });

  it("każda lista ma własną pamięć", () => {
    writeStoredLeadFilters(7, only({ client: "Bank Północny" }));
    writeStoredLeadFilters(7, only({ who: "9" }), "allocation-proposals");
    expect(readStoredLeadFilters(7)).toEqual(only({ client: "Bank Północny" }));
    expect(readStoredLeadFilters(7, "allocation-proposals")).toEqual(only({ who: "9" }));
    expect(Object.keys(window.localStorage).sort()).toEqual([
      "nexus:allocation-proposals-filters:7",
      "nexus:new-job-leads-filters:7",
    ]);
  });

  it("wyczyszczone filtry usuwają wpis", () => {
    writeStoredLeadFilters(7, only({ who: "9" }));
    writeStoredLeadFilters(7, EMPTY_LEAD_FILTERS);
    expect(window.localStorage.length).toBe(0);
  });

  it("bez konta niczego nie zapisuje ani nie czyta", () => {
    writeStoredLeadFilters(null, only({ client: "Bank Północny" }));
    expect(window.localStorage.length).toBe(0);
    expect(readStoredLeadFilters(undefined)).toEqual(EMPTY_LEAD_FILTERS);
  });

  it("zepsuty wpis i obce wartości nie wywracają listy", () => {
    window.localStorage.setItem("nexus:new-job-leads-filters:7", "{nie json");
    expect(readStoredLeadFilters(7)).toEqual(EMPTY_LEAD_FILTERS);
    window.localStorage.setItem(
      "nexus:new-job-leads-filters:7",
      JSON.stringify({ client: 5, cat: "4", prio: "pilne", extra: "x" }),
    );
    expect(readStoredLeadFilters(7)).toEqual(only({ cat: "4" }));
  });

  it("zablokowana pamięć przeglądarki = praca bez pamięci", () => {
    const blocked = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    const full = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    expect(readStoredLeadFilters(7)).toEqual(EMPTY_LEAD_FILTERS);
    expect(() => writeStoredLeadFilters(7, only({ who: "9" }))).not.toThrow();
    blocked.mockRestore();
    full.mockRestore();
  });
});
