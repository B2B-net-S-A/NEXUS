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

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.patch).mockResolvedValue({ data: {} } as never);
  vi.mocked(api.get).mockResolvedValue({
    data: [
      { id: 11, name: "Prowadząca Rekruterka", role: "recruiter", roles: [] },
      { id: 21, name: "Anna Współpracowniczka", role: "sourcer", roles: [] },
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
    expect(screen.queryByText("Rekruter prowadzący")).not.toBeInTheDocument();
    expect(screen.queryByText("Delivery Lead")).not.toBeInTheDocument();
    expect(screen.getByText(/zmienia Delivery Lead/)).toBeInTheDocument();
    // Lista klientów nie jest potrzebna; katalog osób tylko dla pola
    // „Współpracownicy” (decyzja 29.09.2026 — dopisuje każdy, kto redaguje).
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

  it("pole „Współpracownicy” pokazuje wyłącznie ręcznych, bez prowadzącego", async () => {
    renderModal("content");
    const chips = await screen.findByRole("list", { name: "Wybrani współpracownicy" });
    expect(chips).toHaveTextContent("Bartek Drugi");
    expect(chips).not.toHaveTextContent("Cała Kategoria");
  });

  it("zapis dopisuje i zdejmuje współpracowników po PATCH-u", async () => {
    const user = userEvent.setup();
    renderModal("content");
    await user.click(
      await screen.findByRole("button", { name: "Usuń Bartek Drugi ze współpracowników" }),
    );
    await user.click(screen.getByRole("button", { name: /^Współpracownicy:/ }));
    await user.click(await screen.findByRole("option", { name: /Anna Współpracowniczka/ }));
    // Prowadzącej nie da się wybrać — serwer odpowiedziałby 409.
    expect(screen.queryByRole("option", { name: /Prowadząca Rekruterka/ })).toBeNull();
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledTimes(1));
    expect(api.post).toHaveBeenCalledWith("/api/jobs/7/collaborators", { user_id: 21 });
    expect(api.delete).toHaveBeenCalledWith("/api/jobs/7/collaborators/22");
  });

  it("awaria zapisu współpracowników zostawia okno z komunikatem", async () => {
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
    await user.click(await screen.findByRole("button", { name: /^Współpracownicy:/ }));
    await user.click(await screen.findByRole("option", { name: /Anna Współpracowniczka/ }));
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    expect(await screen.findByText(/Rekrutacja zapisana, ale/)).toBeInTheDocument();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("domyślnie pełny formularz (klient, budżet, zespół)", () => {
    vi.mocked(phase5Api.clientsLookup).mockResolvedValue({ data: [] } as never);
    vi.mocked(api.get).mockResolvedValue({ data: [] } as never);
    renderModal();
    expect(screen.getByText("Klient")).toBeInTheDocument();
    expect(screen.getByText(/Budżet PLN\/h/)).toBeInTheDocument();
  });
});
