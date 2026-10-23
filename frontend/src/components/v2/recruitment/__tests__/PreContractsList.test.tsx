import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PreContractRequest } from "@/lib/api/preContracts";
import { useAuthStore } from "@/store/auth";

const row = {
  id: 7,
  candidate_id: 31,
  candidate_name: "Anna Testowa",
  job_id: 12,
  job_title: "Analityk systemowy",
  state: "requested",
  state_label: "Prośba",
  badge: { label: "Czeka", tone: "neutral", detail: "" },
  is_open: true,
  needed_before: "cv_sent",
  needed_before_label: "przed wysłaniem CV",
  requested_at: "2026-10-22T10:00:00Z",
  watchers: [],
  watching: false,
  can_withdraw: false,
  can_decide_penalty: false,
  events: [],
} as unknown as PreContractRequest;

vi.mock("next/navigation", () => ({
  usePathname: () => "/jobs/umowy-przedwstepne",
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/url-selection", () => ({ useUrlWriter: () => ({ replaceUrl: vi.fn() }) }));
vi.mock("@/lib/api/preContracts", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/api/preContracts")>();
  return {
    ...actual,
    usePreContractList: () => ({
      isLoading: false,
      isError: false,
      isSuccess: true,
      data: { items: [row], counts: { todo: 1 } },
      refetch: vi.fn(),
    }),
  };
});

import { PreContractsList } from "@/components/v2/recruitment/PreContractsList";

function setUser(roles: string[]) {
  useAuthStore.setState({
    user: {
      id: 5, email: "u@example.com", name: "U", role: roles[0], roles,
      profile_completed: true, profile_completed_at: null, force_password_change: false,
    } as never,
    realUser: null,
    hydrated: true,
  });
}

describe("lista „Umowy przedwstępne”", () => {
  beforeEach(() => setUser(["recruiter"]));

  it("rekruterowi osoba prowadzi do panelu osoby w rekrutacji", () => {
    render(<PreContractsList />);
    expect(screen.getByRole("link", { name: "Anna Testowa" })).toHaveAttribute(
      "href",
      "/jobs/12?candidate=31",
    );
  });

  it("Radzie nadzorczej osoba jest tekstem — panel osoby jest dla niej zamknięty", () => {
    setUser(["board"]);
    render(<PreContractsList />);
    expect(screen.getByText("Anna Testowa")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Anna Testowa" })).toBeNull();
  });
});
