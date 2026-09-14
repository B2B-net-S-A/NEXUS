/**
 * „Skopiuj jako template" — szablon to TREŚĆ starej roli, nie jej cykl życia.
 *
 * Audyt B40: kopia zamkniętej rekrutacji startowała jako „Zamknięta" z
 * deadline'em sprzed lat, bo `jobToForm(src)` zerował tylko tytuł i klienta.
 * Backend (`jobs.py`, `from_job_id`) statusu i terminu NIE kopiuje — wysyłał je
 * sam formularz.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AddJobModal } from "@/components/AppShell";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
  getClientTeam: vi.fn(),
  clientsLookup: vi.fn(),
  listTemplates: vi.fn(),
  previewHistory: vi.fn(),
  generateJob: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/jobs",
}));

vi.mock("@/lib/use-debounced-value", () => ({
  useDebouncedValue: (value: unknown) => value,
}));

vi.mock("@/components/jobs/CompetenceCategoryPicker", () => ({
  CompetenceCategoryPicker: () => null,
}));

vi.mock("@/components/jobs/AutoAssignedCollaborators", () => ({
  AutoAssignedCollaborators: () => null,
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: mocks.get,
    post: mocks.post,
    patch: mocks.patch,
    delete: mocks.delete,
  },
  aiWriterApi: { generateJob: mocks.generateJob },
  candidateProfileApi: { updateLocation: vi.fn() },
  clientTeamApi: { get: mocks.getClientTeam },
  phase5Api: { clientsLookup: mocks.clientsLookup },
  pipelineTemplatesApi: { list: mocks.listTemplates },
  requestHistoryApi: { preview: mocks.previewHistory },
}));

const SOURCE_JOB_ID = 9;

function renderFromTemplate() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AddJobModal onClose={() => {}} onSuccess={() => {}} fromJobId={SOURCE_JOB_ID} />
    </QueryClientProvider>,
  );
}

describe("AddJobModal — kopia rekrutacji jako szablon (audyt B40)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.clientsLookup.mockResolvedValue({ data: [{ id: 42, name: "Klient testowy" }] });
    mocks.listTemplates.mockResolvedValue({ data: [] });
    mocks.getClientTeam.mockResolvedValue({ data: { tacs: [], delivery_leads: [] } });
    mocks.previewHistory.mockResolvedValue({
      data: {
        closed: [],
        in_progress: [],
        skill_frequency: {},
        meta: { sql_count: 0, voyage_count: 0, total: 0, skill_freq_sample: 0 },
      },
    });
    mocks.get.mockImplementation((url: string) => {
      if (url === `/api/jobs/${SOURCE_JOB_ID}`) {
        return Promise.resolve({
          data: {
            id: SOURCE_JOB_ID,
            title: "Programista (zamknięta rola)",
            client_id: 42,
            status: "closed",
            deadline: "2023-10-23T00:00:00Z",
            description: "Opis do ponownego użycia",
            priority: "high",
            recruitment_type: "body_leasing",
          },
        });
      }
      if (url === "/api/jobs/train-names") return Promise.resolve({ data: { items: [] } });
      return Promise.resolve({ data: [] });
    });
  });

  it("nowy szkic dziedziczy treść, ale NIE status „Zamknięta” ani stary deadline", async () => {
    renderFromTemplate();

    // Treść z szablonu weszła — dowód, że prefill w ogóle się wykonał.
    await waitFor(() =>
      expect(screen.getByPlaceholderText("Opis stanowiska...")).toHaveValue(
        "Opis do ponownego użycia",
      ),
    );
    expect(screen.getByRole("combobox", { name: "Priorytet" })).toHaveValue("high");

    // Cykl życia jest stanem NOWEGO procesu: szkic bez terminu.
    expect(screen.getByRole("combobox", { name: "Status" })).toHaveValue("draft");
    expect(screen.getByLabelText("Deadline")).toHaveValue("");
    // Tytuł i klient nadal do świadomego wpisania.
    expect(screen.getByPlaceholderText("Senior Java Developer")).toHaveValue("");
  });
});
