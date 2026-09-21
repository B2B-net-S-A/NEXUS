import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  capability: { current: true },
  get: vi.fn(),
  editor: vi.fn(),
}));

vi.mock("@/hooks/useCapability", () => ({ useCapability: () => mocks.capability.current }));
vi.mock("@/lib/matching-requirements", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/matching-requirements")>()),
  matchingRequirementsApi: { get: mocks.get, save: vi.fn() },
}));
// Edytor ma własne testy (`SavedRequestSearch.test.tsx`); tu liczy się, że to
// TEN SAM komponent co w dawnej zakładce i że dostaje właściwą bramkę.
vi.mock("@/components/talent-radar/SavedRequestRequirements", () => ({
  SavedRequestRequirements: (p: { jobId: number; canEdit: boolean; onSaved: () => void }) => {
    mocks.editor(p);
    return <div data-testid="requirements-editor" data-can-edit={String(p.canEdit)} />;
  },
}));

import { RequestRequirementsRail } from "@/components/v2/recruitment/RequestRequirementsRail";

const contract = {
  version: 1 as const,
  reviewed: true,
  missing_evidence_policy: "review" as const,
  all_of: [
    { any_of: ["java", "kotlin"], level: "must" as const, source: "request" as const, evidence: "" },
    { any_of: ["aws"], level: "must" as const, source: "request" as const, evidence: "" },
    { any_of: ["kafka"], level: "nice" as const, source: "request" as const, evidence: "" },
  ],
};

function mount(props: Partial<React.ComponentProps<typeof RequestRequirementsRail>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onSaved = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <RequestRequirementsRail jobId={42} onSaved={onSaved} {...props} />
    </QueryClientProvider>,
  );
  return { onSaved };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.capability.current = true;
});

describe("RequestRequirementsRail — „Wymagania z requestu”", () => {
  it("listuje „Musi mieć” i „Mile widziane” z zapisanych wymagań oraz to samo wejście edycji", async () => {
    mocks.get.mockResolvedValue(contract);
    const { onSaved } = mount();
    expect(await screen.findByText("Musi mieć · 2")).toBeInTheDocument();
    expect(screen.getByText("java lub kotlin")).toBeInTheDocument();
    expect(screen.getByText("aws")).toBeInTheDocument();
    expect(screen.getByText("Mile widziane · 1")).toBeInTheDocument();
    expect(screen.getByText("kafka")).toBeInTheDocument();
    expect(screen.getByText("z requestu")).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith(42);
    expect(screen.getByTestId("requirements-editor")).toHaveAttribute("data-can-edit", "true");
    expect(mocks.editor).toHaveBeenLastCalledWith({ jobId: 42, canEdit: true, onSaved });
  });

  it("ta sama bramka co dawna zakładka: bez `job.update` albo w trybie odczytu edycja jest wyłączona", async () => {
    mocks.get.mockResolvedValue(contract);
    mocks.capability.current = false;
    mount();
    await screen.findByText("Musi mieć · 2");
    expect(screen.getByTestId("requirements-editor")).toHaveAttribute("data-can-edit", "false");
  });

  it("tryb odczytu wyłącza edycję nawet roli z `job.update`", async () => {
    mocks.get.mockResolvedValue(contract);
    mount({ readOnly: true });
    await screen.findByText("Musi mieć · 2");
    expect(screen.getByTestId("requirements-editor")).toHaveAttribute("data-can-edit", "false");
  });

  it("awaria odczytu to alert, nie „brak wymagań”", async () => {
    mocks.get.mockRejectedValue({ response: { status: 500, data: { detail: [{ msg: "x" }] } } });
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się wczytać wymagań");
    expect(screen.queryByText(/Musi mieć/)).toBeNull();
  });
});
