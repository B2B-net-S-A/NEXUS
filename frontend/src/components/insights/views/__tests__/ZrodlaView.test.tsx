/**
 * Zakładka „Źródła”: liczba otwiera osoby, źródło rozwija ogłoszenia, rekruter nie
 * rozwija cudzych linków, a awaria nie wygląda jak pustka.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ZrodlaView } from "@/components/insights/views/ZrodlaView";

const sources = vi.fn();
const sourceOffers = vi.fn();
const sourceLinks = vi.fn();
const sourcePeople = vi.fn();
let role = "admin";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/insights",
}));

vi.mock("@/lib/insights-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/insights-api")>();
  return {
    ...actual,
    insightsApi: {
      ...actual.insightsApi,
      sources: (...args: unknown[]) => sources(...args),
      sourceOffers: (...args: unknown[]) => sourceOffers(...args),
      sourceLinks: (...args: unknown[]) => sourceLinks(...args),
      sourcePeople: (...args: unknown[]) => sourcePeople(...args),
    },
  };
});

vi.mock("@/components/insights/sections/InsightsLinkPeople", () => ({
  InsightsLinkPeople: () => <div data-testid="link-people" />,
}));
vi.mock("@/components/insights/sections/InsightsInviteLinks", () => ({
  InsightsInviteLinks: () => <div data-testid="invite-links" />,
}));

vi.mock("@/store/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/store/auth")>();
  return {
    ...actual,
    useAuthStore: (selector: (s: { user: { role: string; roles: string[] } }) => unknown) =>
      selector({ user: { role, roles: [role] } }),
    hasRole: (_user: unknown, ...roles: string[]) => roles.includes(role),
  };
});

const counts = (people: number, cv_sent = 0) => ({
  people,
  applications: people + 1,
  fresh: 1,
  in_process: 1,
  verified: 0,
  cv_sent,
  hired: 0,
});

const TABLE = {
  period: {
    kind: "custom",
    start: "2026-10-04T00:00:00+02:00",
    end: "2026-11-04T00:00:00+01:00",
    timezone: "Europe/Warsaw",
  },
  counted_from: "2026-10-12T00:00:00+02:00",
  portals: [
    { source: "pracuj", label: "Pracuj.pl", ...counts(200, 5) },
    { source: "jjit", label: "JustJoin.IT i RocketJobs", ...counts(0) },
  ],
  portals_total: counts(200, 5),
  career: [
    { source: "link_general", label: "Link ogólny rekrutera", ...counts(3) },
    { source: "link_job", label: "Linki do rekrutacji", ...counts(0) },
  ],
  career_total: counts(3),
  new_candidates_total: 10,
  new_candidates_without_source: 2,
};

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ZrodlaView />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  role = "admin";
  [sources, sourceOffers, sourceLinks, sourcePeople].forEach((fn) => fn.mockReset());
  sources.mockResolvedValue(TABLE);
});

describe("ZrodlaView", () => {
  it("pisze wniosek i okno przycięte do 12.10", async () => {
    renderView();
    expect(await screen.findByText(/Portale dały 200 osób, strona kariery 3/)).toBeTruthy();
    expect(screen.getByText(/z Pracuj\.pl 2,5/)).toBeTruthy();
    expect(screen.getByText(/liczymy od 12\.10\.2026/)).toBeTruthy();
  });

  it("klik w liczbę otwiera osoby z tym filtrem, zero nie jest przyciskiem", async () => {
    sourcePeople.mockResolvedValue({
      total: 5,
      rows: [
        {
          candidate_id: 7,
          name: "Fikcyjna Osoba",
          applied_at: "2026-10-20T10:00:00+02:00",
          applications: 1,
          offer: "Tester",
          link_owner: null,
          link_job_id: null,
          link_job_title: null,
          stage: "interview",
          job_id: 9,
          job_title: "Fikcyjna rekrutacja",
        },
      ],
    });
    renderView();
    fireEvent.click(await screen.findByTestId("sources-cell-pracuj:cv_sent"));
    const panel = await screen.findByTestId("sources-people-panel");
    expect(within(panel).getByText("CV wysłane: 5")).toBeTruthy();
    await waitFor(() => expect(within(panel).getByText("Fikcyjna Osoba")).toBeTruthy());
    // `interview` to na Tablicy kolumna „Zweryfikowany”.
    expect(within(panel).getByText("Zweryfikowany")).toBeTruthy();
    expect(sourcePeople.mock.calls[0][1]).toMatchObject({ source: "pracuj", metric: "cv_sent" });
    expect(screen.queryByTestId("sources-cell-jjit:people")).toBeNull();
    expect(within(panel).getByRole("button", { name: /Pokaż więcej/ })).toBeTruthy();
    expect(within(panel).getByRole("button", { name: /Eksportuj/ })).toBeTruthy();
  });

  it("gdy lista różni się od liczby, panel pisze obie", async () => {
    sourcePeople.mockResolvedValue({ total: 4, rows: [] });
    renderView();
    fireEvent.click(await screen.findByTestId("sources-cell-pracuj:cv_sent"));
    expect(await screen.findByTestId("sources-people-reconcile")).toBeTruthy();
  });

  it("klik w portal rozwija ogłoszenia, a ich liczba zawęża osoby", async () => {
    sourceOffers.mockResolvedValue({ total: 9, rows: [{ offer: "Tester", ...counts(4, 2) }] });
    sourcePeople.mockResolvedValue({ total: 2, rows: [] });
    renderView();
    fireEvent.click(await screen.findByRole("button", { name: "Pracuj.pl" }));
    expect(await screen.findByText("Tester")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Pokaż wszystkie ogłoszenia \(9\)/ })).toBeTruthy();
    fireEvent.click(screen.getByTestId("sources-cell-pracuj/Tester:cv_sent"));
    await waitFor(() =>
      expect(sourcePeople.mock.calls[0][1]).toMatchObject({ source: "pracuj", offer: "Tester" }),
    );
  });

  it("rekruter nie rozwija linków i nie eksportuje, a widzi kanały zamiast osób", async () => {
    role = "recruiter";
    sourcePeople.mockResolvedValue({ total: 5, rows: [] });
    renderView();
    await screen.findByText("Link ogólny rekrutera");
    expect(screen.queryByRole("button", { name: "Link ogólny rekrutera" })).toBeNull();
    expect(screen.getByTestId("invite-links")).toBeTruthy();
    expect(screen.queryByTestId("link-people")).toBeNull();
    fireEvent.click(screen.getByTestId("sources-cell-pracuj:cv_sent"));
    const panel = await screen.findByTestId("sources-people-panel");
    await waitFor(() => expect(sourcePeople).toHaveBeenCalled());
    expect(within(panel).queryByRole("button", { name: /Eksportuj/ })).toBeNull();
  });

  it("awaria nie wygląda jak pusta tabela", async () => {
    sources.mockRejectedValue(new Error("boom"));
    renderView();
    await waitFor(() => expect(screen.queryByTestId("sources-table")).toBeNull());
    expect(await screen.findByText(/Źródła kandydatów/)).toBeTruthy();
  });
});
