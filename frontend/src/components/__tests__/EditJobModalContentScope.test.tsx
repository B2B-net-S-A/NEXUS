import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { EditJobModal } from "@/components/AppShell";
import api, { phase5Api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  aiWriterApi: {},
  phase5Api: { clientsLookup: vi.fn() },
  pipelineTemplatesApi: {},
  requestHistoryApi: {},
}));

// Domyślnie prawdziwe zachowanie; test „błąd HM” podmienia oba na raz.
const hmMocks = vi.hoisted(() => ({ forceFailure: false }));
vi.mock("@/lib/hiring-manager", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/hiring-manager")>();
  return {
    ...actual,
    sameChoice: (...args: Parameters<typeof actual.sameChoice>) =>
      hmMocks.forceFailure ? false : actual.sameChoice(...args),
    saveHiringManager: (...args: Parameters<typeof actual.saveHiringManager>) =>
      hmMocks.forceFailure
        ? Promise.reject({ response: { status: 500, data: { detail: "awaria" } } })
        : actual.saveHiringManager(...args),
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  hmMocks.forceFailure = false;
  vi.mocked(api.patch).mockResolvedValue({ data: {} } as never);
  vi.mocked(api.get).mockResolvedValue({
    data: [
      { id: 11, name: "Pierwsza Rekruterka", role: "recruiter", roles: [] },
      { id: 21, name: "Anna Kolejna", role: "recruiter", roles: [] },
      { id: 22, name: "Bartek Drugi", role: "recruiter", roles: [] },
    ],
  } as never);
  vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
  vi.mocked(api.delete).mockResolvedValue({ data: {} } as never);
});

const job = {
  id: 7,
  title: "Senior Java Developer",
  client_id: 3,
  description: "Stary opis",
  requirements: "Java",
  rate_budget_hourly: 150,
  recruiter_id: 11,
  delivery_lead_id: 12,
  status: "published",
  collaborators: [
    { id: 22, name: "Bartek Drugi", source: "manual" },
    { id: 30, name: "Cała Kategoria", source: "auto_cc" },
  ],
};

function renderModal(scope?: "full" | "content") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EditJobModal job={job} onClose={() => {}} onSuccess={() => {}} scope={scope} />
    </QueryClientProvider>,
  );
}

describe("EditJobModal — edycja treści przez rekrutera (22.09.2026)", () => {
  it("scope=content pokazuje tylko opis i wymagania, bez list klientów i osób", () => {
    renderModal("content");
    expect(screen.getByDisplayValue("Stary opis")).toBeInTheDocument();
    expect(screen.queryByText("Klient")).not.toBeInTheDocument();
    expect(screen.queryByText(/Budżet PLN\/h/)).not.toBeInTheDocument();
    // Pierwszego rekrutera zmienia Delivery Lead albo Head of Recruitment.
    expect(screen.queryByText("Rekruter")).not.toBeInTheDocument();
    expect(screen.queryByText("Delivery Lead")).not.toBeInTheDocument();
    expect(screen.getByText(/zmienia Delivery Lead/)).toBeInTheDocument();
    expect(
      screen.getByText(/Rekrutera przydziela Delivery Lead albo Head of Recruitment/),
    ).toBeInTheDocument();
    // Lista klientów nie jest potrzebna; katalog osób tylko dla pola
    // „Kolejne osoby” (decyzja 29.09.2026 — dopisuje każdy, kto redaguje).
    expect(phase5Api.clientsLookup).not.toHaveBeenCalled();
    for (const [url] of vi.mocked(api.get).mock.calls) {
      expect(url).toBe("/api/users");
    }
  });

  it("scope=content wysyła w PATCH wyłącznie opis i wymagania", async () => {
    const user = userEvent.setup();
    renderModal("content");
    const description = screen.getByDisplayValue("Stary opis");
    await user.clear(description);
    await user.type(description, "Nowy opis");
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    expect(api.patch).toHaveBeenCalledWith("/api/jobs/7", {
      description: "Nowy opis",
      requirements: "Java",
    });
  });

  it("pole „Kolejne osoby” pokazuje wyłącznie dopisanych ręcznie, bez pierwszego rekrutera i bez całej kategorii", async () => {
    renderModal("content");
    expect(screen.getByText("Kolejne osoby")).toBeInTheDocument();
    expect(screen.queryByText("Współpracownicy")).not.toBeInTheDocument();
    const chips = await screen.findByRole("list", { name: "Wybrane kolejne osoby" });
    expect(chips).toHaveTextContent("Bartek Drugi");
    expect(chips).not.toHaveTextContent("Cała Kategoria");
  });

  it("zapis dopisuje i zdejmuje kolejne osoby po PATCH-u", async () => {
    const user = userEvent.setup();
    renderModal("content");
    await user.click(
      await screen.findByRole("button", { name: "Zdejmij Bartek Drugi" }),
    );
    await user.click(screen.getByRole("button", { name: /^Kolejne osoby:/ }));
    await user.click(await screen.findByRole("option", { name: /Anna Kolejna/ }));
    // Pierwszej rekruterki nie da się wybrać — serwer odpowiedziałby 409.
    expect(screen.queryByRole("option", { name: /Pierwsza Rekruterka/ })).toBeNull();
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledTimes(1));
    expect(api.post).toHaveBeenCalledWith("/api/jobs/7/collaborators", { user_id: 21 });
    expect(api.delete).toHaveBeenCalledWith("/api/jobs/7/collaborators/22");
  });

  it("awaria zapisu kolejnych osób zostawia okno z komunikatem", async () => {
    vi.mocked(api.post).mockRejectedValue({
      response: { status: 403, data: { detail: "Nie masz uprawnień do edycji rekrutacji." } },
    } as never);
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <EditJobModal job={job} onClose={() => {}} onSuccess={onSuccess} scope="content" />
      </QueryClientProvider>,
    );
    await user.click(await screen.findByRole("button", { name: /^Kolejne osoby:/ }));
    await user.click(await screen.findByRole("option", { name: /Anna Kolejna/ }));
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    expect(
      await screen.findByText(
        "Rekrutacja zapisana, ale nie zapisano kolejnych osób (Nie masz uprawnień do edycji rekrutacji.).",
      ),
    ).toBeInTheDocument();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("błąd zapisu hiring managera nie pomija zapisu kolejnych osób", async () => {
    hmMocks.forceFailure = true;
    vi.mocked(phase5Api.clientsLookup).mockResolvedValue({ data: [] } as never);
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <EditJobModal job={job} onClose={() => {}} onSuccess={onSuccess} scope="full" />
      </QueryClientProvider>,
    );
    await user.click(
      await screen.findByRole("button", { name: "Zdejmij Bartek Drugi" }),
    );
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith("/api/jobs/7/collaborators/22"),
    );
    expect(await screen.findByText(/Rekrutacja zapisana, ale hiring manager nie/)).toBeInTheDocument();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("domyślnie pełny formularz (klient, budżet, zespół)", () => {
    vi.mocked(phase5Api.clientsLookup).mockResolvedValue({ data: [] } as never);
    vi.mocked(api.get).mockResolvedValue({ data: [] } as never);
    renderModal();
    expect(screen.getByText("Klient")).toBeInTheDocument();
    expect(screen.getByText(/Budżet PLN\/h/)).toBeInTheDocument();
  });

  it("pełny formularz mówi „Rekruter” i „Kolejne osoby” — bez dawnych nazw (02.10.2026)", () => {
    vi.mocked(phase5Api.clientsLookup).mockResolvedValue({ data: [] } as never);
    vi.mocked(api.get).mockResolvedValue({ data: [] } as never);
    renderModal();
    expect(screen.getByText("Rekruter")).toBeInTheDocument();
    expect(screen.getByText("Kolejne osoby")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "— bez rekrutera —" })).toBeInTheDocument();
    for (const gone of ["Rekruter prowadzący", "Współpracownicy", "— nieprzypisany —"]) {
      expect(screen.queryByText(gone)).not.toBeInTheDocument();
    }
  });

  it("zmiana etykiet nie zmieniła zapisu: pełny formularz dalej wysyła `recruiter_id`", async () => {
    vi.mocked(phase5Api.clientsLookup).mockResolvedValue({ data: [] } as never);
    const user = userEvent.setup();
    renderModal();
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    const [url, body] = vi.mocked(api.patch).mock.calls[0];
    expect(url).toBe("/api/jobs/7");
    expect(body).toMatchObject({ recruiter_id: 11, delivery_lead_id: 12 });
  });
});

describe("EditJobModal — status bez szkiców (04.10.2026)", () => {
  function renderWithJob(overrides: Record<string, unknown>, onRequestPublish?: () => void) {
    vi.mocked(phase5Api.clientsLookup).mockResolvedValue({ data: [] } as never);
    const onClose = vi.fn();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <EditJobModal
          job={{ ...job, ...overrides }}
          onClose={onClose}
          onSuccess={() => {}}
          onRequestPublish={onRequestPublish}
        />
      </QueryClientProvider>,
    );
    return { onClose };
  }

  it("rekrutacja w pracy ma tylko „W pracy” i „Zamknięta” — bez szkicu", () => {
    renderWithJob({});
    const status = screen.getByLabelText("Status");
    const options = Array.from(status.querySelectorAll("option")).map((o) => o.textContent);
    expect(options).toEqual(["W pracy", "Zamknięta"]);
    expect(screen.queryByRole("option", { name: "Draft" })).toBeNull();
  });

  it("zapis bez zmiany statusu nie wysyła `status`; zamknięcie wysyła `closed`", async () => {
    const user = userEvent.setup();
    renderWithJob({});
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.patch).mock.calls[0][1]).not.toHaveProperty("status");

    vi.mocked(api.patch).mockClear();
    await user.selectOptions(screen.getByLabelText("Status"), "closed");
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.patch).mock.calls[0][1]).toMatchObject({ status: "closed" });
  });

  it("zamknięta: status tylko do odczytu i „Otwórz ponownie” zamyka okno i otwiera dialog", async () => {
    const onRequestPublish = vi.fn();
    const user = userEvent.setup();
    const { onClose } = renderWithJob({ status: "closed" }, onRequestPublish);
    expect(screen.getByTestId("job-status-readonly")).toHaveTextContent("Zamknięta");
    await user.click(screen.getByRole("button", { name: "Otwórz ponownie" }));
    expect(onClose).toHaveBeenCalled();
    expect(onRequestPublish).toHaveBeenCalled();
  });

  it("stary szkic: „Szkic (do dokończenia)” i link „Dokończ i opublikuj” do `?reopen=1`", () => {
    renderWithJob({ status: "draft" });
    expect(screen.getByTestId("job-status-readonly")).toHaveTextContent("Szkic (do dokończenia)");
    expect(screen.getByRole("link", { name: "Dokończ i opublikuj" })).toHaveAttribute(
      "href",
      "/jobs/7?reopen=1",
    );
  });

  it("odmowa `handoff_regression` pokazuje zdanie i braki", async () => {
    vi.mocked(api.patch).mockRejectedValueOnce({
      response: {
        status: 422,
        data: {
          detail: {
            code: "handoff_regression",
            message: "Rekrutacja w pracy straciłaby wymagane pole.",
            blockers: [{ code: "deadline", message: "Podaj termin." }],
          },
        },
      },
    });
    const user = userEvent.setup();
    renderWithJob({});
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    expect(
      await screen.findByText("Rekrutacja w pracy straciłaby wymagane pole. Podaj termin."),
    ).toBeInTheDocument();
  });
});

