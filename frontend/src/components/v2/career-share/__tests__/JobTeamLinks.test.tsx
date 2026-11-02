import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobTeamLinks } from "../JobTeamLinks";
import api from "@/lib/api";
import { useAuthStore } from "@/store/auth";

vi.mock("@/lib/api", () => {
  const client = { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() };
  return { default: client, api: client };
});

const ROWS = [
  {
    owner_id: 7,
    owner_name: "Marta Fikcyjna",
    slug: "java-7kq2",
    label: "Ogłoszenie",
    created_at: "2026-10-29T10:00:00Z",
    visits: 7,
    applications: 1,
    state: "active",
  },
  {
    owner_id: 8,
    owner_name: "Damian Testowy",
    slug: "java-1abc",
    label: null,
    created_at: "2026-10-29T10:00:00Z",
    visits: 2,
    applications: 0,
    state: "revoked",
  },
];

function renderIt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <JobTeamLinks enabled jobId={101} />
    </QueryClientProvider>,
  );
}

function loginAs(role: string) {
  useAuthStore.setState({ user: { id: 7, role, roles: [role] } as never });
}

describe("JobTeamLinks", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it("Delivery Lead widzi linki zespołu z sumą, swoim wierszem i stanem", async () => {
    loginAs("delivery_lead");
    vi.mocked(api.get).mockResolvedValue({ data: ROWS });
    renderIt();
    expect(await screen.findByTestId("job-team-links")).toBeInTheDocument();
    expect(screen.getByText("9 wejść · 1 zgłoszeń")).toBeInTheDocument();
    expect(screen.getByText("(Ty)")).toBeInTheDocument();
    expect(screen.getByText("Własny link")).toBeInTheDocument();
    expect(screen.getByText("wycofany")).toBeInTheDocument();
  });

  it("rekruter nie widzi sekcji i nie pyta API", () => {
    loginAs("recruiter");
    const { container } = renderIt();
    expect(container).toBeEmptyDOMElement();
    expect(api.get).not.toHaveBeenCalled();
  });

  it("awaria mówi, że się nie udało, zamiast znikać", async () => {
    loginAs("head_of_recruitment");
    vi.mocked(api.get).mockRejectedValue(new Error("boom"));
    renderIt();
    expect(await screen.findByText(/Nie udało się wczytać linków zespołu/)).toBeInTheDocument();
  });
});
