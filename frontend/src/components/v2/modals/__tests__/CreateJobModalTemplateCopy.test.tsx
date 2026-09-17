/**
 * „Skopiuj jako template" (`fromJobId`) — szablon to TREŚĆ starej roli, nie
 * jej cykl życia (audyt B40, `AddJobModalTemplateCopy.test.tsx` sprzed PR 4).
 * `CreateJobModal` nie ma już pól status/priority/deadline w ogóle — payload
 * ich nie niesie, więc nie ma czego zerować.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  getClientTeam: vi.fn(),
  routerPush: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.routerPush }),
}));

vi.mock("@/lib/use-debounced-value", () => ({
  useDebouncedValue: (value: unknown) => value,
}));

vi.mock("@/lib/use-job-draft", () => ({
  useJobDraft: () => ({
    restorable: null,
    acceptRestorable: vi.fn(),
    clear: vi.fn(),
  }),
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => mocks.get(...args),
    post: (...args: unknown[]) => mocks.post(...args),
  },
  aiWriterApi: { generateJob: vi.fn() },
  clientTeamApi: { get: (...args: unknown[]) => mocks.getClientTeam(...args) },
}));

vi.mock("@/components/clients/ClientSinglePicker", () => ({
  ClientSinglePicker: ({
    value,
    onChange,
  }: {
    value: { id: number; name: string } | null;
    onChange: (client: { id: number; name: string } | null) => void;
  }) => (
    <button type="button" onClick={() => onChange({ id: 42, name: "Acme" })}>
      {value ? value.name : "Wybierz klienta…"}
    </button>
  ),
}));

vi.mock("@/components/v2/jobs/SimilarRequestsBanner", () => ({
  SimilarRequestsBanner: () => null,
}));

import { CreateJobModal } from "@/components/v2/modals/CreateJobModal";
import { useAuthStore, type User } from "@/store/auth";

const dlUser = {
  id: 3,
  name: "Delivery Lead",
  email: "dl@example.com",
  role: "delivery_lead",
  roles: ["delivery_lead"],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
  effective_section_access: { pipeline: "write" },
} satisfies User;

const SOURCE_JOB_ID = 9;

function renderFromTemplate() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CreateJobModal
        onClose={() => {}}
        onSuccess={() => {}}
        fromJobId={SOURCE_JOB_ID}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({
    user: dlUser,
    realUser: null,
    token: "token",
    hydrated: true,
  });
  mocks.getClientTeam.mockResolvedValue({ data: { tacs: [], delivery_leads: [] } });
  mocks.post.mockResolvedValue({ data: { id: 777 } });
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
          location: "Warszawa",
          remote_policy: "hybrid",
          onsite_days_per_week: 2,
          rate_budget_hourly: 150,
          recruitment_type: "sales_project",
          must_skills: [{ name: "Python" }, { name: "Django" }],
          priority: "high",
        },
      });
    }
    return Promise.resolve({ data: [] });
  });
});

describe("CreateJobModal — „Skopiuj jako template”", () => {
  it("prefilluje puste pola z /api/jobs/9, tytuł i klient zostają puste do świadomego wpisania", async () => {
    renderFromTemplate();

    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith(`/api/jobs/${SOURCE_JOB_ID}`));

    await waitFor(() =>
      expect(screen.getByPlaceholderText("Opis stanowiska...")).toHaveValue(
        "Opis do ponownego użycia",
      ),
    );
    expect(screen.getByPlaceholderText("Java, Spring, Kafka")).toHaveValue(
      "Python, Django",
    );
    expect(screen.getByLabelText("Miasto biura")).toHaveValue("Warszawa");
    expect(screen.getByLabelText("Tryb pracy")).toHaveValue("hybrid");
    expect(screen.getByLabelText("Dni w biurze / tydzień")).toHaveValue(2);
    expect(
      screen.getByLabelText("Budżet PLN/h dla kandydata"),
    ).toHaveValue(150);
    expect(screen.getByLabelText("Typ rekrutacji")).toHaveValue(
      "sales_project",
    );

    // Tytuł i klient — DL wpisuje/potwierdza sam.
    expect(screen.getByPlaceholderText("Senior Java Developer")).toHaveValue("");
    expect(
      screen.getByRole("button", { name: "Wybierz klienta…" }),
    ).toBeInTheDocument();
  });

  it("payload niesie from_job_id + copy_questions, bez status/priority/deadline (nie istnieją w tym modalu)", async () => {
    renderFromTemplate();
    await waitFor(() =>
      expect(screen.getByPlaceholderText("Opis stanowiska...")).toHaveValue(
        "Opis do ponownego użycia",
      ),
    );

    await userEvent.type(
      screen.getByPlaceholderText("Senior Java Developer"),
      "Nowy tytuł roli",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Wybierz klienta…" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Dodaj rekrutację" }));

    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    const [, payload] = mocks.post.mock.calls[0] as [string, Record<string, unknown>];
    expect(payload.from_job_id).toBe(SOURCE_JOB_ID);
    expect(payload.copy_questions).toBe(true);
    expect("status" in payload).toBe(false);
    expect("priority" in payload).toBe(false);
    expect("deadline" in payload).toBe(false);
    expect("requirements" in payload).toBe(false);
  });

  it("„Cofnij szablon” czyści dokładnie te pola, które szablon wypełnił", async () => {
    renderFromTemplate();
    await waitFor(() =>
      expect(screen.getByPlaceholderText("Opis stanowiska...")).toHaveValue(
        "Opis do ponownego użycia",
      ),
    );

    await userEvent.click(screen.getByRole("button", { name: "Cofnij szablon" }));

    expect(screen.getByPlaceholderText("Opis stanowiska...")).toHaveValue("");
    expect(screen.getByPlaceholderText("Java, Spring, Kafka")).toHaveValue("");
    expect(screen.getByLabelText("Miasto biura")).toHaveValue("");
    expect(
      screen.queryByRole("button", { name: "Cofnij szablon" }),
    ).not.toBeInTheDocument();
  });
});
