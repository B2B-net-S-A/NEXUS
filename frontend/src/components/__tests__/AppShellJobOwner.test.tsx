import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  routerPush: vi.fn(),
  generateJob: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.routerPush }),
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

function renderAddJob() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AddJobModal onClose={() => {}} onSuccess={() => {}} />
    </QueryClientProvider>,
  );
}

async function selectForOption(optionName: string): Promise<HTMLSelectElement> {
  const option = await screen.findByRole("option", { name: optionName });
  const select = option.closest("select");
  if (!select) throw new Error(`No select found for option: ${optionName}`);
  return select;
}

const userRows = [
  { id: 7, name: "Anna TAC", email: "anna@example.com", role: "tac" },
  { id: 8, name: "Ola TAC", email: "ola@example.com", role: "tac" },
];

const assignment = (
  id: number,
  name: string,
  firstPriority: boolean,
) => ({
  id,
  user_id: id,
  name,
  email: `${name.split(" ")[0].toLowerCase()}@example.com`,
  role: "tac",
  created_at: "2026-08-03T10:00:00Z",
  is_first_priority_for_tac: firstPriority,
});

describe("AddJobModal — jawny owner requestu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.clientsLookup.mockResolvedValue({
      data: [{ id: 42, name: "Acme" }],
    });
    mocks.listTemplates.mockResolvedValue({ data: [] });
    mocks.previewHistory.mockResolvedValue({
      data: {
        closed: [],
        in_progress: [],
        skill_frequency: {},
        meta: { sql_count: 0, voyage_count: 0, total: 0, skill_freq_sample: 0 },
      },
    });
    mocks.get.mockImplementation((url: string) => {
      if (url === "/api/users") return Promise.resolve({ data: userRows });
      if (url === "/api/jobs/train-names") {
        return Promise.resolve({ data: { items: [] } });
      }
      if (url === "/api/clients/42/contacts") {
        return Promise.resolve({ data: [] });
      }
      return Promise.resolve({ data: [] });
    });
    mocks.post.mockResolvedValue({ data: { id: 501 } });
  });

  it("reviews AI description without changing requirements, salary or deriving seniority from priority", async () => {
    mocks.generateJob.mockResolvedValue({data: {description: "Nowy opis", requirements: "Kubernetes", salary_range_suggestion: "30000 PLN", source: "claude"}});
    const user = userEvent.setup();
    renderAddJob();
    await user.type(screen.getByPlaceholderText("Senior Java Developer"), "Python Developer");
    await user.type(screen.getByPlaceholderText("Opis stanowiska..."), "Oryginalny opis");
    await user.type(screen.getByPlaceholderText("Wymagania techniczne..."), "Python lub Java");
    await user.selectOptions(screen.getByRole("combobox", {name: "Priorytet"}), "urgent");
    await user.click(screen.getByRole("button", {name: /Generuj AI/}));
    await screen.findByRole("textbox", {name: "Szkic opisu do zatwierdzenia"});
    expect(mocks.generateJob).toHaveBeenCalledWith(expect.objectContaining({seniority: undefined, skills: ["Python lub Java"]}));
    expect(screen.getByPlaceholderText("Opis stanowiska...")).toHaveValue("Oryginalny opis");
    expect(screen.getByRole("spinbutton", {name: "Wynagrodzenie min (PLN/mies.)"})).toHaveValue(null);
    await user.click(screen.getByRole("button", {name: "Zastosuj sprawdzony opis"}));
    expect(screen.getByPlaceholderText("Opis stanowiska...")).toHaveValue("Nowy opis");
    expect(screen.getByPlaceholderText("Wymagania techniczne...")).toHaveValue("Python lub Java");
    expect(screen.getByRole("spinbutton", {name: "Wynagrodzenie min (PLN/mies.)"})).toHaveValue(null);
  });

  it("nie wybiera ownera z osobistego priorytetu, gdy klient ma kilku TAC-ów", async () => {
    mocks.getClientTeam.mockResolvedValue({
      data: {
        tacs: [
          assignment(7, "Anna TAC", true),
          assignment(8, "Ola TAC", false),
        ],
        delivery_leads: [],
      },
    });
    const user = userEvent.setup();
    renderAddJob();

    await user.type(
      screen.getByPlaceholderText("Senior Java Developer"),
      "Senior Java Developer",
    );
    await user.selectOptions(await selectForOption("Acme"), "42");

    const owner = await screen.findByRole("combobox", {
      name: "Owner requestu (TAC)",
    });
    await waitFor(() => expect(owner).toBeRequired());
    expect(owner).toHaveValue("");
    expect(
      screen.getByText(/Klient ma 2 równorzędnych TAC-ów/i),
    ).toBeInTheDocument();

    await user.selectOptions(owner, "7");
    expect(screen.getByText("✓ Owner requestu wybrany jawnie")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dodaj rekrutację" }));

    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/jobs",
        expect.objectContaining({ client_id: 42, tac_id: 7 }),
      ),
    );
  });

  it("prefilluje jedynego TAC-a klienta niezależnie od flagi priorytetu", async () => {
    mocks.getClientTeam.mockResolvedValue({
      data: {
        tacs: [assignment(7, "Anna TAC", false)],
        delivery_leads: [],
      },
    });
    const user = userEvent.setup();
    renderAddJob();

    await user.selectOptions(await selectForOption("Acme"), "42");

    const owner = await screen.findByRole("combobox", {
      name: "Owner requestu (TAC)",
    });
    await waitFor(() => expect(owner).toHaveValue("7"));
    expect(owner).not.toBeRequired();
    expect(
      screen.getByText("✓ Prefill: jedyny TAC przypisany do klienta"),
    ).toBeInTheDocument();
  });
});
