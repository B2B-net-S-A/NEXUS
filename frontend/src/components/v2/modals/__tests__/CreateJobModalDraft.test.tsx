/**
 * Szkic w `localStorage` (PR 4) — baner przywracania i strażnik zamknięcia
 * brudnego formularza (Escape / „Anuluj"). `AppShellModal.test.tsx` (pinuje
 * `Modal` przez `AddClientModal`) NIETKNIĘTY — ten plik testuje wyłącznie
 * `CreateJobModal`/`DiscardDraftDialog`.
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
import { writeJobDraft, readJobDraft } from "@/lib/job-draft-storage";

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

const FILLED_DRAFT = {
  title: "Senior Java Developer",
  clientId: 42,
  clientName: "Acme",
  recruitmentType: "body_leasing",
  description: "Opis ze szkicu",
  mustHaveInput: "",
  location: "",
  remotePolicy: "",
  onsiteDaysPerWeek: "",
  rateBudgetHourly: "",
  salaryMin: "",
  salaryMax: "",
};

function renderModal(onClose = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <CreateJobModal onClose={onClose} onSuccess={vi.fn()} />
    </QueryClientProvider>,
  );
  return { onClose };
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  useAuthStore.setState({
    user: dlUser,
    realUser: null,
    token: "token",
    hydrated: true,
  });
  mocks.getClientTeam.mockResolvedValue({ data: { tacs: [], delivery_leads: [] } });
});

describe("CreateJobModal — przywracanie szkicu", () => {
  it("pokazuje baner, gdy w localStorage jest zapisany szkic tego użytkownika", async () => {
    writeJobDraft(dlUser.id, FILLED_DRAFT);
    renderModal();

    expect(
      await screen.findByText(/Masz niezapisany szkic z/),
    ).toBeInTheDocument();
  });

  it("nie pokazuje banera bez zapisanego szkicu", async () => {
    renderModal();
    await screen.findByPlaceholderText("Senior Java Developer");
    expect(
      screen.queryByText(/Masz niezapisany szkic z/),
    ).not.toBeInTheDocument();
  });

  it("„Przywróć szkic” wypełnia formularz i chowa baner", async () => {
    writeJobDraft(dlUser.id, FILLED_DRAFT);
    renderModal();
    await screen.findByText(/Masz niezapisany szkic z/);

    await userEvent.click(screen.getByRole("button", { name: "Przywróć szkic" }));

    expect(screen.getByPlaceholderText("Senior Java Developer")).toHaveValue(
      "Senior Java Developer",
    );
    expect(screen.getByPlaceholderText("Opis stanowiska...")).toHaveValue(
      "Opis ze szkicu",
    );
    expect(screen.queryByText(/Masz niezapisany szkic z/)).not.toBeInTheDocument();
  });

  it("nie kasuje nierozstrzygniętego szkicu pustym auto-zapisem tuż po otwarciu", async () => {
    // Regresja: pierwszy debounce PUSTEGO formularza (modal właśnie się
    // otworzył) mógłby skasować zapisany szkic, zanim DL zdąży kliknąć
    // „Przywróć szkic" — `useJobDraft` musi wstrzymać autosave, dopóki
    // baner jest nierozstrzygnięty.
    writeJobDraft(dlUser.id, FILLED_DRAFT);
    renderModal();
    await screen.findByText(/Masz niezapisany szkic z/);

    await new Promise((r) => setTimeout(r, 700));

    expect(readJobDraft(dlUser.id)?.form).toEqual(FILLED_DRAFT);
  });

  it("„Odrzuć” kasuje zapisany szkic i chowa baner bez zmiany formularza", async () => {
    writeJobDraft(dlUser.id, FILLED_DRAFT);
    renderModal();
    await screen.findByText(/Masz niezapisany szkic z/);

    await userEvent.click(screen.getByRole("button", { name: "Odrzuć" }));

    expect(screen.queryByText(/Masz niezapisany szkic z/)).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Senior Java Developer")).toHaveValue("");
    expect(readJobDraft(dlUser.id)).toBeNull();
  });
});

describe("CreateJobModal — strażnik zamknięcia formularza", () => {
  it("pusty formularz zamyka się od razu, bez pytania", async () => {
    const { onClose } = renderModal();
    await userEvent.click(screen.getByRole("button", { name: "Anuluj" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByText("Formularz ma niezapisane zmiany."),
    ).not.toBeInTheDocument();
  });

  it("brudny formularz pyta przed zamknięciem", async () => {
    const { onClose } = renderModal();
    await userEvent.type(
      screen.getByPlaceholderText("Senior Java Developer"),
      "Coś tam",
    );
    await userEvent.click(screen.getByRole("button", { name: "Anuluj" }));

    expect(
      await screen.findByText("Formularz ma niezapisane zmiany."),
    ).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("„Wróć do formularza” zamyka dialog i zostawia formularz otwarty", async () => {
    const { onClose } = renderModal();
    await userEvent.type(
      screen.getByPlaceholderText("Senior Java Developer"),
      "Coś tam",
    );
    await userEvent.click(screen.getByRole("button", { name: "Anuluj" }));
    await screen.findByText("Formularz ma niezapisane zmiany.");

    await userEvent.click(screen.getByRole("button", { name: "Wróć do formularza" }));

    expect(
      screen.queryByText("Formularz ma niezapisane zmiany."),
    ).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByPlaceholderText("Senior Java Developer")).toHaveValue(
      "Coś tam",
    );
  });

  it("„Odrzuć szkic” kasuje localStorage i zamyka modal", async () => {
    const { onClose } = renderModal();
    await userEvent.type(
      screen.getByPlaceholderText("Senior Java Developer"),
      "Coś tam",
    );
    await userEvent.click(screen.getByRole("button", { name: "Anuluj" }));
    await screen.findByText("Formularz ma niezapisane zmiany.");

    await userEvent.click(screen.getByRole("button", { name: "Odrzuć szkic" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(readJobDraft(dlUser.id)).toBeNull();
  });

  it("„Zamknij i zachowaj szkic” zapisuje bieżący formularz i zamyka modal", async () => {
    const { onClose } = renderModal();
    await userEvent.type(
      screen.getByPlaceholderText("Senior Java Developer"),
      "Coś tam",
    );
    await userEvent.click(screen.getByRole("button", { name: "Anuluj" }));
    await screen.findByText("Formularz ma niezapisane zmiany.");

    await userEvent.click(
      screen.getByRole("button", { name: "Zamknij i zachowaj szkic" }),
    );

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(readJobDraft(dlUser.id)?.form.title).toBe("Coś tam");
  });
});

describe("CreateJobModal — autosave", () => {
  it("zapisuje formularz do localStorage po debounce, bez nierozstrzygniętego banera", async () => {
    renderModal();
    await userEvent.type(
      screen.getByPlaceholderText("Senior Java Developer"),
      "Autosave Test",
    );

    await waitFor(
      () => expect(readJobDraft(dlUser.id)?.form.title).toBe("Autosave Test"),
      { timeout: 2000 },
    );
  });
});
