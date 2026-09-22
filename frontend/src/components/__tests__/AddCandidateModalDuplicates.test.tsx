import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AddCandidateModal } from "@/components/AppShell";
import api, { phase5Api } from "@/lib/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/candidates",
}));
vi.mock("@/components/jobs/AutoAssignedCollaborators", () => ({
  AutoAssignedCollaborators: () => null,
}));
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
  pipelineTemplatesApi: { list: vi.fn() },
  requestHistoryApi: { preview: vi.fn() },
  clientTeamApi: { get: vi.fn() },
}));

const apiPost = vi.mocked(api.post);

const HIT = {
  candidate_id: 41,
  name: "Jan",
  lastname: "Kowalski",
  email: "jan@example.com",
  match_score: 0.95,
  match_reasons: ["email"],
};

function renderModal(onSuccess = vi.fn(), onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AddCandidateModal onClose={onClose} onSuccess={onSuccess} />
    </QueryClientProvider>,
  );
  return { onSuccess, onClose };
}

function duplicateCalls() {
  return apiPost.mock.calls.filter(([url]) => url === "/api/candidates/check-duplicates");
}

function createCalls() {
  return apiPost.mock.calls.filter(([url]) => url === "/api/candidates");
}

async function fillIdentity(user: ReturnType<typeof userEvent.setup>, email: string) {
  await user.type(screen.getByPlaceholderText("Jan"), "Jan");
  await user.type(screen.getByPlaceholderText("Kowalski"), "Kowalski");
  await user.type(screen.getByPlaceholderText("jan@mail.pl"), email);
}

describe("AddCandidateModal — automatyczne sprawdzanie duplikatów", () => {
  beforeEach(() => {
    apiPost.mockReset();
    vi.mocked(api.get).mockResolvedValue({ data: [] } as never);
    vi.mocked(phase5Api.clientsLookup).mockResolvedValue({ data: [] } as never);
  });

  it("nie ma już ręcznego przycisku, a rzadziej używane pola są pod „Więcej danych”", () => {
    renderModal();
    expect(screen.queryByRole("button", { name: /Sprawdź duplikaty/ })).toBeNull();
    const details = screen.getByText("Więcej danych").closest("details");
    expect(details).not.toBeNull();
    expect(within(details as HTMLElement).getByPlaceholderText("https://linkedin.com/in/...")).toBeInTheDocument();
    expect(details).not.toContainElement(screen.getByPlaceholderText("Warszawa"));
    expect(details).not.toContainElement(screen.getByPlaceholderText("+48 500..."));
  });

  it("sprawdza duplikaty sam po debounce", async () => {
    apiPost.mockResolvedValue({ data: [HIT] } as never);
    const user = userEvent.setup();
    renderModal();

    await user.type(screen.getByPlaceholderText("jan@mail.pl"), "jan@example.com");

    await waitFor(() => expect(duplicateCalls().length).toBeGreaterThan(0), { timeout: 2000 });
    expect(await screen.findByText(/Znaleziono 1 podobnego kandydata/)).toBeInTheDocument();
    expect(duplicateCalls().at(-1)?.[1]).toMatchObject({ email: "jan@example.com" });
  });

  it("szybki zapis przed końcem debounce i tak sprawdza duplikaty i czeka na decyzję", async () => {
    apiPost.mockImplementation((url: string) => {
      if (url === "/api/candidates/check-duplicates") {
        return Promise.resolve({ data: [HIT] } as never);
      }
      return Promise.resolve({ data: { id: 99 } } as never);
    });
    const user = userEvent.setup();
    const { onSuccess } = renderModal();

    await fillIdentity(user, "jan@example.com");
    await user.click(screen.getByRole("button", { name: "Dodaj kandydata" }));

    expect(await screen.findByRole("link", { name: "Otwórz istniejącego" })).toHaveAttribute(
      "href",
      "/candidates/41",
    );
    expect(duplicateCalls().length).toBeGreaterThan(0);
    expect(createCalls()).toHaveLength(0);
    expect(onSuccess).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Zapisz mimo to" }));

    await waitFor(() => expect(createCalls()).toHaveLength(1));
    expect(onSuccess).toHaveBeenCalledWith("Kandydat dodany pomyślnie");
  });

  it("imię, nazwisko i LinkedIn bez kontaktu też sprawdzają duplikaty i blokują zapis", async () => {
    apiPost.mockImplementation((url: string) =>
      Promise.resolve({ data: url === "/api/candidates" ? { id: 1 } : [HIT] } as never),
    );
    const user = userEvent.setup();
    renderModal();

    await user.type(screen.getByPlaceholderText("Jan"), "Jan");
    await user.type(screen.getByPlaceholderText("Kowalski"), "Kowalski");
    await user.click(screen.getByText("Więcej danych"));
    await user.type(screen.getByPlaceholderText("https://linkedin.com/in/..."), "https://linkedin.com/in/jan");
    await user.click(screen.getByRole("button", { name: "Dodaj kandydata" }));

    expect(await screen.findByRole("button", { name: "Zapisz mimo to" })).toBeInTheDocument();
    expect(duplicateCalls().at(-1)?.[1]).toMatchObject({ linkedin: "https://linkedin.com/in/jan", name: "Jan" });
    expect(createCalls()).toHaveLength(0);
  });

  it("nazwisko wpisane po sprawdzeniu e-maila wymusza nowe sprawdzenie przed zapisem", async () => {
    apiPost.mockImplementation((url: string, body?: unknown) => {
      if (url === "/api/candidates") return Promise.resolve({ data: { id: 1 } } as never);
      const lastname = (body as { lastname?: string } | undefined)?.lastname;
      return Promise.resolve({ data: lastname === "Kowalski" ? [HIT] : [] } as never);
    });
    const user = userEvent.setup();
    renderModal();

    await user.type(screen.getByPlaceholderText("jan@mail.pl"), "nowy@example.com");
    await waitFor(() => expect(duplicateCalls().length).toBeGreaterThan(0), { timeout: 2000 });
    await user.type(screen.getByPlaceholderText("Jan"), "Jan");
    await user.type(screen.getByPlaceholderText("Kowalski"), "Kowalski");
    await user.click(screen.getByRole("button", { name: "Dodaj kandydata" }));

    expect(await screen.findByRole("button", { name: "Zapisz mimo to" })).toBeInTheDocument();
    expect(createCalls()).toHaveLength(0);
  });

  it("zapisuje od razu, gdy sprawdzenie nie znajduje trafień", async () => {
    apiPost.mockImplementation((url: string) =>
      Promise.resolve({ data: url === "/api/candidates" ? { id: 1 } : [] } as never),
    );
    const user = userEvent.setup();
    const { onSuccess } = renderModal();

    await fillIdentity(user, "nowy@example.com");
    await user.click(screen.getByRole("button", { name: "Dodaj kandydata" }));

    await waitFor(() => expect(createCalls()).toHaveLength(1));
    expect(duplicateCalls().length).toBeGreaterThan(0);
    expect(onSuccess).toHaveBeenCalled();
  });

  it("odrzuca spóźnioną odpowiedź dla starego e-maila", async () => {
    let releaseStale: (value: unknown) => void = () => undefined;
    apiPost.mockImplementation((url: string, body?: unknown) => {
      if (url !== "/api/candidates/check-duplicates") {
        return Promise.resolve({ data: {} } as never);
      }
      const email = (body as { email?: string }).email;
      if (email === "stary@example.com") {
        return new Promise((resolve) => {
          releaseStale = resolve;
        }) as never;
      }
      return Promise.resolve({ data: [] } as never);
    });
    const user = userEvent.setup();
    renderModal();

    const emailInput = screen.getByPlaceholderText("jan@mail.pl");
    await user.type(emailInput, "stary@example.com");
    await waitFor(() => expect(duplicateCalls()).toHaveLength(1), { timeout: 2000 });

    await user.clear(emailInput);
    await user.type(emailInput, "nowy@example.com");
    await waitFor(() => expect(duplicateCalls()).toHaveLength(2), { timeout: 2000 });

    releaseStale({ data: [HIT] });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByText(/podobnego kandydata/)).toBeNull();
  });
});
