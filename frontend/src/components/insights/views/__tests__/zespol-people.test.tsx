/**
 * Zespół → Ludzie: byli pracownicy w jednym wierszu i sortowanie kolumn
 * (prośba z zespołu, 19.10.2026).
 *
 * Reguły pod ochroną:
 *
 * 1. **Konto wyłączone schodzi do wiersza „Byli w zespole (N)”** z sumami —
 *    liczby nie znikają, tylko przestają zajmować wiersze listy.
 * 2. **„Pokaż byłych członków zespołu” przywraca ich jako zwykłe wiersze**
 *    z plakietką „był(a) w zespole”, wspólnie dla obu zakładek.
 * 3. **Klik w nagłówek sortuje**, `aria-sort` mówi, jak; wiersze zbiorcze
 *    zostają pod listą osób.
 * 4. **Aktywny rekruter bez ruchu ma wiersz z zerami** (20.10.2026) — nowa
 *    osoba nie może wyglądać, jakby jej nie było w zespole.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { ZespolView } from "../ZespolView";
import { useAuthStore } from "@/store/auth";

const PERIOD = {
  kind: "month",
  start: "2026-10-01T00:00:00+02:00",
  end: "2026-11-01T00:00:00+01:00",
  timezone: "Europe/Warsaw",
};

function personRow(
  user_id: number,
  name: string,
  extra: Record<string, unknown> = {},
) {
  return {
    user_id,
    name,
    role: "recruiter",
    is_active: true,
    verifications: 5,
    recommendations: 1,
    interviews: 0,
    placements: 0,
    previous_placements: 0,
    verifications_per_workday: 1,
    precision_pct: null,
    ...extra,
  };
}

const PEOPLE = {
  period: PERIOD,
  rows: [
    personRow(1, "Anna Test", { recommendations: 2, placements: 1 }),
    personRow(2, "Jan Kowalski", { recommendations: 6, placements: 3 }),
    personRow(3, "Ewa Była", { is_active: false, recommendations: 4, placements: 2 }),
    personRow(4, "Olga Była", { is_active: false, recommendations: 1, interviews: 2 }),
  ],
  workdays: 10,
  precision_target_pct: 75,
  low_precision_pct: 50,
  totals: {
    verifications: 20,
    recommendations: 13,
    interviews: 2,
    placements: 6,
    precision_pct: null,
    people: 4,
    unattributed: 0,
  },
  previous_totals: { verifications: 0, recommendations: 0, interviews: 0, placements: 0 },
};

function dlLead(dl_id: number, dl_name: string, extra: Record<string, unknown> = {}) {
  return {
    dl_id,
    dl_name,
    is_active: true,
    requests: 4,
    vacancies: 4,
    placements: 1,
    hit_ratio: 25,
    fill_rate: null,
    open_requests: 2,
    target_achieved: null,
    clients: [],
    ...extra,
  };
}

const DL = {
  period: { ...PERIOD, kind: "year", start: "2026-01-01T00:00:00+01:00" },
  hit_ratio_target_pct: 30,
  leads: [
    dlLead(10, "Marek Test", { requests: 8 }),
    dlLead(11, "Piotr Były", { is_active: false, requests: 3, open_requests: 1, placements: 2 }),
  ],
  unattributed: { requests: 0, placements: 0 },
};

function respond() {
  mocks.get.mockImplementation((url: string) => {
    if (url === "/api/insights/team/people") return Promise.resolve({ data: PEOPLE });
    if (url === "/api/insights/delivery-leads/portfolio") return Promise.resolve({ data: DL });
    if (url === "/api/insights/performance-flags") {
      return Promise.resolve({ data: { flags_by_user: {}, types: [] } });
    }
    // Lejek i „Do uwagi” nie są tematem — wczytują się bez końca.
    return new Promise(() => {});
  });
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ZespolView />
    </QueryClientProvider>,
  );
}

function bodyRows(table: HTMLElement): string[] {
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) => row.textContent ?? "");
}

async function peopleTable(): Promise<HTMLElement> {
  renderView();
  await screen.findByText("Anna Test");
  return screen.getByText("Anna Test").closest("table") as HTMLElement;
}

describe("Zespół → Ludzie", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    respond();
    useAuthStore.setState({
      user: {
        id: 99,
        role: "head_of_recruitment",
        roles: ["head_of_recruitment"],
        analytics_capabilities: ["view_team_kpi"],
      },
    } as never);
  });

  it("byli pracownicy domyślnie stoją jednym wierszem z sumami", async () => {
    const table = await peopleTable();
    const rows = bodyRows(table);
    expect(rows).toHaveLength(3);
    const former = within(table).getByText(/Byli w zespole \(2\)/).closest("tr")!;
    expect(former.textContent).toContain("Ewa Była, Olga Była");
    const cells = within(former).getAllByRole("cell").map((cell) => cell.textContent);
    // Weryf./dzień —, CV 4+1, rozmowy 0+2, akceptacje 0, placementy 2+0,
    // w drodze —, precyzja —, zmiana —.
    expect(cells.slice(1)).toEqual(["—", "5", "2", "0", "2", "—", "—", "—"]);
    expect(within(table).queryByText("był(a) w zespole")).toBeNull();
  });

  it("„Pokaż byłych członków zespołu” przywraca ich jako zwykłe wiersze, bez wiersza zbiorczego", async () => {
    const table = await peopleTable();
    fireEvent.click(screen.getByRole("switch", { name: "Pokaż byłych członków zespołu" }));
    expect(within(table).queryByText(/Byli w zespole/)).toBeNull();
    expect(within(table).getByText("Ewa Była")).toBeTruthy();
    expect(within(table).getAllByText("był(a) w zespole")).toHaveLength(2);
  });

  it("klik w nagłówek sortuje malejąco, drugi rosnąco; wiersz zbiorczy zostaje na dole", async () => {
    const table = await peopleTable();
    const header = within(table).getByRole("columnheader", { name: "CV wysłane" });
    expect(header.getAttribute("aria-sort")).toBe("none");
    // Bez kliknięcia — kolejność z API.
    expect(bodyRows(table)[0]).toContain("Anna Test");

    fireEvent.click(within(header).getByRole("button"));
    expect(header.getAttribute("aria-sort")).toBe("descending");
    let rows = bodyRows(table);
    expect(rows[0]).toContain("Jan Kowalski");
    expect(rows[1]).toContain("Anna Test");
    expect(rows[2]).toContain("Byli w zespole");

    fireEvent.click(within(header).getByRole("button"));
    expect(header.getAttribute("aria-sort")).toBe("ascending");
    rows = bodyRows(table);
    expect(rows[0]).toContain("Anna Test");
    expect(rows[2]).toContain("Byli w zespole");
  });

  it("aktywny rekruter bez ruchu stoi z zerami, inna rola bez ruchu idzie do dopisku", async () => {
    const zero = {
      verifications: 0,
      recommendations: 0,
      interviews: 0,
      placements: 0,
      verifications_per_workday: 0,
    };
    const people = {
      ...PEOPLE,
      rows: [
        ...PEOPLE.rows,
        personRow(5, "Nowa Rekruterka", zero),
        personRow(6, "Cichy Lead", { ...zero, role: "delivery_lead" }),
      ],
    };
    mocks.get.mockImplementation((url: string) => {
      if (url === "/api/insights/team/people") return Promise.resolve({ data: people });
      if (url === "/api/insights/performance-flags") {
        return Promise.resolve({ data: { flags_by_user: {}, types: [] } });
      }
      return new Promise(() => {});
    });
    const table = await peopleTable();
    const row = within(table).getByText("Nowa Rekruterka").closest("tr")!;
    // Weryf./dzień, CV, rozmowy, akceptacje („—”: odpowiedź bez pola), placementy.
    expect(within(row).getAllByRole("cell").map((cell) => cell.textContent).slice(1, 6)).toEqual([
      "0",
      "0",
      "0",
      "—",
      "0",
    ]);
    expect(within(table).queryByText("Cichy Lead")).toBeNull();
    expect(screen.getByText(/Pominięto osoby bez ruchu w tym okresie: 1\./)).toBeTruthy();
  });

  it("zakładka Delivery Leadzi: ten sam przełącznik i wiersz zbiorczy", async () => {
    await peopleTable();
    fireEvent.click(screen.getByRole("button", { name: "Delivery Leadzi" }));
    await screen.findByText("Marek Test");
    const table = screen.getByText("Marek Test").closest("table") as HTMLElement;
    const former = within(table).getByText(/Byli w zespole \(1\)/).closest("tr")!;
    expect(within(former).getAllByRole("cell").map((cell) => cell.textContent).slice(1)).toEqual([
      "3",
      "1",
      "2",
      "—",
    ]);

    fireEvent.click(screen.getByRole("switch", { name: "Pokaż byłych członków zespołu" }));
    expect(within(table).queryByText(/Byli w zespole/)).toBeNull();
    expect(within(table).getByText("był(a) w zespole")).toBeTruthy();

    const header = within(table).getByRole("columnheader", { name: "Rekrutacje" });
    fireEvent.click(within(header).getByRole("button"));
    expect(header.getAttribute("aria-sort")).toBe("descending");
    expect(bodyRows(table)[0]).toContain("Marek Test");
    expect(bodyRows(table)[1]).toContain("Piotr Były");
  });
});
