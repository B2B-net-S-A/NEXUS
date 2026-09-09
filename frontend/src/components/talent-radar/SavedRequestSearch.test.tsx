import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, test, vi } from "vitest";
import { SavedRequestSearch } from "./SavedRequestSearch";
import { SavedRequestRequirements } from "./SavedRequestRequirements";

const mocks = vi.hoisted(() => ({ start: vi.fn(), page: vi.fn(), save: vi.fn(), list: vi.fn() }));
vi.mock("@/store/auth", () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ user: { id: 7, role: "admin" } }) }));
vi.mock("@/hooks/useCapability", () => ({ useCapability: () => true }));
vi.mock("@/lib/api", async importOriginal => ({ ...await importOriginal<typeof import("@/lib/api")>(), jobsApi: { list: (...args: unknown[]) => mocks.list(...args) } }));
vi.mock("@/lib/matching-requirements", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/matching-requirements")>(),
  matchingRequirementsApi: {
    get: async () => ({ version: 1, reviewed: false, missing_evidence_policy: "review", all_of: [{ any_of: ["python", "java"], level: "must", source: "request", evidence: "Python or Java" }] }),
    save: (...args: unknown[]) => mocks.save(...args),
  },
}));
vi.mock("@/lib/full-candidate-search-api", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/full-candidate-search-api")>(),
  candidateSearchApi: { start: (...args: unknown[]) => mocks.start(...args), page: (...args: unknown[]) => mocks.page(...args) },
}));

function mount(ui: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);
}
beforeEach(() => {
  sessionStorage.clear(); vi.clearAllMocks();
  mocks.list.mockResolvedValue({ data: { items: [{ id: 42, title: "Python request", client_name: "Acme", unrelated_private_field: "not-for-storage" }], total: 1 } });
  mocks.start.mockResolvedValue({ run_id: "same-run", state: "queued" });
  mocks.save.mockResolvedValue({});
  mocks.page.mockResolvedValue({ run_id: "same-run", state: "complete", counts: { population: 60000, evaluated: 60000, pending: 0, failed: 0, eligible: 0, excluded: 60000, needs_verification: 0 }, results: [], versions: {}, ranking_complete: true, next_offset: null, total_after_threshold: 0 });
});

test("saved Radar request starts by job ID and shares the pipeline run reference", async () => {
  mount(<SavedRequestSearch />);
  fireEvent.click(await screen.findByRole("button", { name: "Python request · Acme" }));
  fireEvent.click(await screen.findByRole("button", { name: "Szukaj w całej bazie" }));
  await waitFor(() => expect(mocks.start).toHaveBeenCalledWith({ job_id: 42 }));
  await waitFor(() => expect(sessionStorage.getItem("nexus-full-job:7:42")).toBe("same-run"));
  expect(JSON.parse(sessionStorage.getItem("nexus-radar-request:7")!)).toEqual({ id: 42, title: "Python request", client_name: "Acme" });
  expect(mocks.list).toHaveBeenCalledWith({ page: 1, page_size: 20, q: undefined });
});

test("same editor saves an explicitly empty reviewed list; read-only mode prevents mutation", async () => {
  const saved = vi.fn();
  const view = mount(<SavedRequestRequirements jobId={42} canEdit onSaved={saved} />);
  fireEvent.click(screen.getByText("Wymagania wyszukiwania"));
  const must = await screen.findByLabelText("Obowiązkowe");
  expect(must).toHaveValue("python lub java");
  fireEvent.change(must, { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz sprawdzone wymagania" }));
  await waitFor(() => expect(mocks.save).toHaveBeenCalledWith(42, { version: 1, reviewed: true, all_of: [], missing_evidence_policy: "review" }));
  expect(saved).toHaveBeenCalledOnce();
  view.unmount();
  mount(<SavedRequestRequirements jobId={42} canEdit={false} onSaved={saved} />);
  fireEvent.click(screen.getByText("Wymagania wyszukiwania"));
  expect(await screen.findByLabelText("Obowiązkowe")).toBeDisabled();
  expect(screen.queryByRole("button", { name: "Zapisz sprawdzone wymagania" })).not.toBeInTheDocument();
});
