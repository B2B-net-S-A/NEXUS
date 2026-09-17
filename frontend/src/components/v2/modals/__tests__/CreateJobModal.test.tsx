import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  generateJob: vi.fn(),
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
  aiWriterApi: { generateJob: (...args: unknown[]) => mocks.generateJob(...args) },
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
    <button
      type="button"
      onClick={() => onChange({ id: 42, name: "Acme" })}
    >
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

const adminUser = {
  ...dlUser,
  id: 1,
  role: "admin",
  roles: ["admin"],
} satisfies User;

function setUser(user: User) {
  useAuthStore.setState({
    user,
    realUser: null,
    token: "token",
    hydrated: true,
  });
}

function renderModal(props: Partial<React.ComponentProps<typeof CreateJobModal>> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onClose = vi.fn();
  const onSuccess = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <CreateJobModal onClose={onClose} onSuccess={onSuccess} {...props} />
    </QueryClientProvider>,
  );
  return { onClose, onSuccess };
}

async function selectClient() {
  await userEvent.click(screen.getByRole("button", { name: "Wybierz klienta…" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  setUser(dlUser);
  mocks.getClientTeam.mockResolvedValue({ data: { tacs: [], delivery_leads: [] } });
  mocks.post.mockResolvedValue({ data: { id: 501 } });
});

describe("CreateJobModal — pola wymagane", () => {
  it("odmawia zapisu bez tytułu", async () => {
    renderModal();
    await userEvent.click(screen.getByRole("button", { name: "Dodaj rekrutację" }));
    expect(await screen.findByText("Tytuł jest wymagany")).toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("odmawia zapisu bez klienta", async () => {
    renderModal();
    await userEvent.type(
      screen.getByPlaceholderText("Senior Java Developer"),
      "Python Developer",
    );
    await userEvent.click(screen.getByRole("button", { name: "Dodaj rekrutację" }));
    expect(
      await screen.findByText(
        "Wybierz klienta — bez niego nie da się zapisać rekrutacji",
      ),
    ).toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });
});

describe("CreateJobModal — payload", () => {
  it("wysyła client_id jako liczbę, must_skills jako tablicę, remote_policy: null gdy nieustawione", async () => {
    renderModal();
    await userEvent.type(
      screen.getByPlaceholderText("Senior Java Developer"),
      "Python Developer",
    );
    await selectClient();
    await userEvent.type(
      screen.getByPlaceholderText("Java, Spring, Kafka"),
      "Python, Django",
    );
    await userEvent.click(screen.getByRole("button", { name: "Dodaj rekrutację" }));

    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    const [url, payload] = mocks.post.mock.calls[0] as [string, Record<string, unknown>];
    expect(url).toBe("/api/jobs");
    expect(payload.client_id).toBe(42);
    expect(typeof payload.client_id).toBe("number");
    expect(payload.must_skills).toEqual(["Python", "Django"]);
    expect(payload.remote_policy).toBeNull();
  });

  it("NIE wysyła widełek wynagrodzenia dla Delivery Lead", async () => {
    setUser(dlUser);
    renderModal();
    await userEvent.type(
      screen.getByPlaceholderText("Senior Java Developer"),
      "Python Developer",
    );
    await selectClient();
    await userEvent.click(screen.getByRole("button", { name: "Dodaj rekrutację" }));

    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    const [, payload] = mocks.post.mock.calls[0] as [string, Record<string, unknown>];
    expect("salary_min" in payload).toBe(false);
    expect("salary_max" in payload).toBe(false);
    // Puste pole must-have = brak wartości (JSON pomija `undefined`), nie `[]`
    // — pusta tablica zapisałaby kolumnę jako „ustawioną na nic”.
    expect(payload.must_skills).toBeUndefined();
    // Pola techniczne, których modal świadomie nie wysyła — DL twórca
    // ląduje jako `delivery_lead_id` po stronie backendu (PR 1).
    expect("status" in payload).toBe(false);
    expect("priority" in payload).toBe(false);
    expect("deadline" in payload).toBe(false);
    expect("tac_id" in payload).toBe(false);
    expect("delivery_lead_id" in payload).toBe(false);
    expect("recruiter_id" in payload).toBe(false);
  });

  it("wysyła widełki wynagrodzenia dla admina, gdy wypełnione", async () => {
    setUser(adminUser);
    renderModal();
    await userEvent.type(
      screen.getByPlaceholderText("Senior Java Developer"),
      "Python Developer",
    );
    await selectClient();
    await userEvent.type(
      screen.getByLabelText("Wynagrodzenie min (PLN/mies.)"),
      "8000",
    );
    await userEvent.type(
      screen.getByLabelText("Wynagrodzenie max (PLN/mies.)"),
      "12000",
    );
    await userEvent.click(screen.getByRole("button", { name: "Dodaj rekrutację" }));

    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    const [, payload] = mocks.post.mock.calls[0] as [string, Record<string, unknown>];
    expect(payload.salary_min).toBe(8000);
    expect(payload.salary_max).toBe(12000);
  });

  it("Delivery Lead nie widzi w ogóle pól widełek", async () => {
    setUser(dlUser);
    renderModal();
    expect(
      screen.queryByLabelText("Wynagrodzenie min (PLN/mies.)"),
    ).not.toBeInTheDocument();
  });
});

describe("CreateJobModal — „Dni w biurze / tydzień”", () => {
  it("jest spinbuttonem, wyłączonym gdy tryb pracy = remote", async () => {
    renderModal();
    const days = screen.getByLabelText("Dni w biurze / tydzień");
    expect(days).toHaveAttribute("type", "number");
    expect(days).not.toBeDisabled();

    await userEvent.selectOptions(
      screen.getByLabelText("Tryb pracy"),
      "remote",
    );
    expect(days).toBeDisabled();
  });
});

describe("CreateJobModal — lądowanie po zapisie", () => {
  it("bez opisu ląduje na zakładce Championa BEZ &intake=1", async () => {
    renderModal();
    await userEvent.type(
      screen.getByPlaceholderText("Senior Java Developer"),
      "Python Developer",
    );
    await selectClient();
    await userEvent.click(screen.getByRole("button", { name: "Dodaj rekrutację" }));

    await waitFor(() =>
      expect(mocks.routerPush).toHaveBeenCalledWith("/jobs/501?tab=champion"),
    );
  });

  it("z opisem ląduje z &intake=1", async () => {
    renderModal();
    await userEvent.type(
      screen.getByPlaceholderText("Senior Java Developer"),
      "Python Developer",
    );
    await selectClient();
    await userEvent.type(
      screen.getByPlaceholderText("Opis stanowiska..."),
      "Szukamy Pythonistę do zespołu płatności.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Dodaj rekrutację" }));

    await waitFor(() =>
      expect(mocks.routerPush).toHaveBeenCalledWith(
        "/jobs/501?tab=champion&intake=1",
      ),
    );
  });

  it("woła onSuccess z komunikatem po zapisie i zamyka modal", async () => {
    const { onClose, onSuccess } = renderModal();
    await userEvent.type(
      screen.getByPlaceholderText("Senior Java Developer"),
      "Python Developer",
    );
    await selectClient();
    await userEvent.click(screen.getByRole("button", { name: "Dodaj rekrutację" }));

    await waitFor(() =>
      expect(onSuccess).toHaveBeenCalledWith(
        "Rekrutacja utworzona. Uzupełnij Profil Championa, żeby przekazać ją do searchu.",
        { id: 501 },
      ),
    );
    expect(onClose).toHaveBeenCalled();
  });
});

describe("CreateJobModal — szkic AI", () => {
  it("nie nadpisuje opisu, dopóki DL nie kliknie „Zastosuj sprawdzony opis”", async () => {
    mocks.generateJob.mockResolvedValue({
      data: { description: "Nowy opis wygenerowany przez AI", source: "claude" },
    });
    renderModal();
    await userEvent.type(
      screen.getByPlaceholderText("Senior Java Developer"),
      "Python Developer",
    );
    await userEvent.type(
      screen.getByPlaceholderText("Opis stanowiska..."),
      "Oryginalny opis DL-a",
    );

    await userEvent.click(screen.getByRole("button", { name: /Generuj AI/ }));
    await screen.findByRole("textbox", { name: "Szkic opisu do zatwierdzenia" });

    // Szkic czeka na akceptację — pole opisu formularza NIETKNIĘTE.
    expect(screen.getByPlaceholderText("Opis stanowiska...")).toHaveValue(
      "Oryginalny opis DL-a",
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Zastosuj sprawdzony opis" }),
    );
    expect(screen.getByPlaceholderText("Opis stanowiska...")).toHaveValue(
      "Nowy opis wygenerowany przez AI",
    );
  });

  it("„Odrzuć szkic” zamyka podgląd bez zmiany opisu", async () => {
    mocks.generateJob.mockResolvedValue({
      data: { description: "Szkic AI", source: "claude" },
    });
    renderModal();
    await userEvent.type(
      screen.getByPlaceholderText("Senior Java Developer"),
      "Python Developer",
    );
    await userEvent.click(screen.getByRole("button", { name: /Generuj AI/ }));
    await screen.findByRole("textbox", { name: "Szkic opisu do zatwierdzenia" });

    await userEvent.click(screen.getByRole("button", { name: "Odrzuć szkic" }));
    expect(
      screen.queryByRole("textbox", { name: "Szkic opisu do zatwierdzenia" }),
    ).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Opis stanowiska...")).toHaveValue("");
  });
});

describe("CreateJobModal — błędy API", () => {
  it("503 z obiektowym `detail` pokazuje `reason` zamiast wywracać modal", async () => {
    mocks.post.mockRejectedValueOnce({
      response: {
        status: 503,
        data: {
          detail: {
            feature: "job.create",
            reason: "Miesięczny limit AI wyczerpany",
          },
        },
      },
    });
    renderModal();
    await userEvent.type(
      screen.getByPlaceholderText("Senior Java Developer"),
      "Python Developer",
    );
    await selectClient();
    await userEvent.click(screen.getByRole("button", { name: "Dodaj rekrutację" }));

    expect(
      await screen.findByText("Miesięczny limit AI wyczerpany"),
    ).toBeInTheDocument();
    // Formularz przeżył — dialog nadal na ekranie z wypełnioną treścią.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("Senior Java Developer"),
    ).toHaveValue("Python Developer");
  });
});
