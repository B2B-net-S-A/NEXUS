import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  DRAFT_STATE,
  MEASUREMENT_DONE,
  PREVIEW,
  PREVIEW_JOBS,
  panelState,
} from "@/components/settings/ranking/previewFixtures";

import ScoringWeightsPage from "./page";

const mocks = vi.hoisted(() => ({
  user: null as Record<string, unknown> | null,
  search: "",
  panel: vi.fn(),
  saveDraft: vi.fn(),
  discardDraft: vi.fn(),
  measurement: vi.fn(),
  startMeasurement: vi.fn(),
  publish: vi.fn(),
  restore: vi.fn(),
  previewJobs: vi.fn(),
  preview: vi.fn(),
  list: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/settings/scoring",
  useSearchParams: () => new URLSearchParams(mocks.search),
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: mocks.user, hydrated: true }),
  hasRole: (user: { role?: string; roles?: string[] } | null, ...roles: string[]) =>
    !!user && roles.some((role) => new Set([user.role, ...(user.roles ?? [])]).has(role)),
}));

vi.mock("@/lib/api", () => ({
  scoringWeightsApi: {
    panel: mocks.panel,
    saveDraft: mocks.saveDraft,
    discardDraft: mocks.discardDraft,
    measurement: mocks.measurement,
    startMeasurement: mocks.startMeasurement,
    publish: mocks.publish,
    restore: mocks.restore,
    previewJobs: mocks.previewJobs,
    preview: mocks.preview,
    list: mocks.list,
  },
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ScoringWeightsPage />
    </QueryClientProvider>,
  );
}

const HOR = {
  role: "head_of_recruitment",
  roles: ["head_of_recruitment"],
  effective_section_access: { insights: "write" },
};
const DL = {
  role: "delivery_lead",
  roles: ["delivery_lead"],
  effective_section_access: { insights: "read" },
};

describe("Ranking kandydatów — panel wag", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.search = "";
    mocks.panel.mockResolvedValue({ data: panelState() });
    mocks.previewJobs.mockResolvedValue({ data: { jobs: PREVIEW_JOBS } });
    mocks.preview.mockResolvedValue({ data: PREVIEW });
    mocks.list.mockResolvedValue({ data: [] });
  });

  it("„Jak to działa” pokazuje udziały, którymi liczy silnik", async () => {
    mocks.user = DL;
    renderPage();
    expect(await screen.findByText("Z czego składa się „Dop.” — stan na dziś")).toBeInTheDocument();
    expect(screen.getByText("67%")).toBeInTheDocument();
    expect(screen.getByText("17%")).toBeInTheDocument();
  });

  it("Delivery Lead przesuwa suwak dla podglądu, ale nie zapisuje", async () => {
    mocks.user = { ...DL, effective_section_access: { insights: "read" } };
    mocks.panel.mockResolvedValue({ data: panelState({ can_edit: false }) });
    mocks.search = "zakladka=wagi";
    renderPage();
    const slider = await screen.findByLabelText("Umiejętności z listy");
    fireEvent.change(slider, { target: { value: "40" } });
    expect(screen.queryByRole("button", { name: "Sprawdź na historii" })).not.toBeInTheDocument();
    expect(screen.getByText(/Zapisać i opublikować wagi może Head of/)).toBeInTheDocument();
    // Podgląd liczy kolejność w przeglądarce.
    expect(await screen.findByText("Katarzyna Przykładowa")).toBeInTheDocument();
  });

  it("HoR zapisuje szkic i uruchamia pomiar dopiero po zmianie", async () => {
    mocks.user = HOR;
    mocks.search = "zakladka=wagi";
    mocks.saveDraft.mockResolvedValue({ data: DRAFT_STATE });
    mocks.startMeasurement.mockResolvedValue({ data: { measurement: MEASUREMENT_DONE } });
    renderPage();
    const check = await screen.findByRole("button", { name: "Sprawdź na historii" });
    expect(check).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Umiejętności z listy"), { target: { value: "30" } });
    expect(screen.getByText("Szkic — zespół go nie widzi")).toBeInTheDocument();
    mocks.panel.mockResolvedValue({ data: DRAFT_STATE });
    fireEvent.click(check);
    await waitFor(() => expect(mocks.startMeasurement).toHaveBeenCalled());
    expect(mocks.saveDraft).toHaveBeenCalledWith({
      semantic: 60,
      skills: 30,
      location: 5,
      threshold: 70,
    });
  });

  it("zero we wszystkich ważnościach blokuje pomiar z komunikatem", async () => {
    mocks.user = HOR;
    mocks.search = "zakladka=wagi";
    renderPage();
    for (const label of ["Podobieństwo CV do rekrutacji", "Umiejętności z listy", "Lokalizacja i tryb pracy"]) {
      fireEvent.change(await screen.findByLabelText(label), { target: { value: "0" } });
    }
    expect(screen.getByRole("alert")).toHaveTextContent("co najmniej jedną ważność");
    expect(screen.getByRole("button", { name: "Sprawdź na historii" })).toBeDisabled();
  });

  it("spadek > 2 pkt: publikacja dopiero z powodem", async () => {
    mocks.user = HOR;
    mocks.search = "zakladka=historia";
    const result = { ...MEASUREMENT_DONE.result!, needs_reason: true, max_drop_pt: 3 };
    mocks.panel.mockResolvedValue({
      data: { ...DRAFT_STATE, measurement: { ...MEASUREMENT_DONE, result } },
    });
    renderPage();
    const publish = await screen.findByRole("button", { name: "Opublikuj mimo spadku" });
    expect(publish).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText(/DL-e zgłaszają/), {
      target: { value: "świadomie, klient chce stack" },
    });
    expect(publish).toBeEnabled();
  });

  it("szkic bez aktualnego pomiaru nie ma przycisku publikacji", async () => {
    mocks.user = HOR;
    mocks.search = "zakladka=historia";
    mocks.panel.mockResolvedValue({
      data: { ...DRAFT_STATE, measurement: { ...MEASUREMENT_DONE, fresh: false } },
    });
    renderPage();
    expect(await screen.findByText(/nie był jeszcze sprawdzony na historii/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Opublikuj/ })).not.toBeInTheDocument();
  });

  it("awaria odczytu nie wygląda jak pusty panel", async () => {
    mocks.user = HOR;
    mocks.panel.mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("Z czego składa się „Dop.” — stan na dziś")).not.toBeInTheDocument();
  });

  it("profile klienta i osoby widzi tylko admin", async () => {
    mocks.user = { role: "admin", roles: ["admin"], effective_section_access: { insights: "write" } };
    mocks.search = "zakladka=wagi";
    renderPage();
    expect(await screen.findByText("Profile klienta i osoby (administrator)")).toBeInTheDocument();
  });

  it("rekruter nie ma dostępu", () => {
    mocks.user = { role: "recruiter", roles: ["recruiter"], effective_section_access: { insights: "read" } };
    renderPage();
    expect(screen.getByText("Brak dostępu do wag rankingu.")).toBeInTheDocument();
    expect(mocks.panel).not.toHaveBeenCalled();
  });
});
