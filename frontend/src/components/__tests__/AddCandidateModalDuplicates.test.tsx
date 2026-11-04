import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  match_score: 1,
  match_reasons: ["email_exact"],
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

// 12.10.2026 (decyzja Artura): ta sama osoba = ten sam e-mail. Okno pokazywało
// 34 obcych osób jako „podobnych” po końcówce adresu LinkedIn, a „Zapisz mimo
// to” przy tym samym e-mailu serwer i tak odrzucał.
describe("AddCandidateModal — ta sama osoba = ten sam e-mail", () => {
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

  it("sprawdza sam po debounce i pyta wyłącznie o e-mail", async () => {
    apiPost.mockResolvedValue({ data: [HIT] } as never);
    renderModal();

    // `fireEvent`, nie pisanie znak po znaku: na wolnym runnerze cztery pola
    // i opóźnienie sprawdzenia nie mieszczą się w limicie testu.
    fireEvent.change(screen.getByPlaceholderText("Jan"), { target: { value: "Jan" } });
    fireEvent.change(screen.getByPlaceholderText("Kowalski"), { target: { value: "Kowalski" } });
    fireEvent.change(screen.getByPlaceholderText("+48 500..."), { target: { value: "600100200" } });
    fireEvent.change(screen.getByPlaceholderText("jan@mail.pl"), {
      target: { value: "jan@example.com" },
    });

    await waitFor(() => expect(duplicateCalls().length).toBeGreaterThan(0), { timeout: 2000 });
    expect(await screen.findByText("Ten kandydat już jest w bazie")).toBeInTheDocument();
    expect(screen.getByText(/Jan Kowalski · jan@example.com/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Otwórz profil" })).toHaveAttribute("href", "/candidates/41");
    // Telefon, LinkedIn oraz imię i nazwisko nie jadą do sprawdzenia.
    expect(duplicateCalls().at(-1)?.[1]).toEqual({ email: "jan@example.com" });
    expect(screen.queryByText(/score/)).toBeNull();
  });

  it("zajęty e-mail zastępuje przycisk zapisu ramką — bez „Zapisz mimo to”", async () => {
    apiPost.mockImplementation((url: string) => {
      if (url === "/api/candidates/check-duplicates") {
        return Promise.resolve({ data: [HIT] } as never);
      }
      return Promise.resolve({ data: { id: 99 } } as never);
    });
    const user = userEvent.setup();
    const { onSuccess } = renderModal();

    await fillIdentity(user, "jan@example.com");
    // Szybki zapis przed końcem debounce i tak sprawdza e-mail.
    await user.click(screen.getByRole("button", { name: "Dodaj kandydata" }));

    expect(await screen.findByRole("link", { name: "Otwórz profil" })).toHaveAttribute(
      "href",
      "/candidates/41",
    );
    expect(createCalls()).toHaveLength(0);
    expect(onSuccess).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Zapisz mimo to" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Dodaj kandydata" })).toBeNull();
    // Bez wybranego pliku nie ma czego dodawać do profilu.
    expect(screen.queryByRole("button", { name: "Dodaj to CV do profilu" })).toBeNull();
  });

  it("imię, nazwisko i LinkedIn bez e-maila niczego nie sprawdzają i zapisują od razu", async () => {
    apiPost.mockImplementation((url: string) =>
      Promise.resolve({ data: url === "/api/candidates" ? { id: 1 } : [HIT] } as never),
    );
    const user = userEvent.setup();
    const { onSuccess } = renderModal();

    await user.type(screen.getByPlaceholderText("Jan"), "Jan");
    await user.type(screen.getByPlaceholderText("Kowalski"), "Kowalski");
    await user.click(screen.getByText("Więcej danych"));
    await user.type(screen.getByPlaceholderText("https://linkedin.com/in/..."), "linkedin.com");
    await user.click(screen.getByRole("button", { name: "Dodaj kandydata" }));

    await waitFor(() => expect(createCalls()).toHaveLength(1));
    expect(duplicateCalls()).toHaveLength(0);
    expect(onSuccess).toHaveBeenCalledWith("Kandydat dodany pomyślnie");
  });

  it("zmiana e-maila na wolny przywraca przycisk zapisu", async () => {
    apiPost.mockImplementation((url: string, body?: unknown) => {
      if (url === "/api/candidates") return Promise.resolve({ data: { id: 1 } } as never);
      const email = (body as { email?: string } | undefined)?.email;
      return Promise.resolve({ data: email === "jan@example.com" ? [HIT] : [] } as never);
    });
    renderModal();

    const emailInput = screen.getByPlaceholderText("jan@mail.pl");
    fireEvent.change(emailInput, { target: { value: "jan@example.com" } });
    expect(await screen.findByText("Ten kandydat już jest w bazie")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dodaj kandydata" })).toBeNull();

    fireEvent.change(emailInput, { target: { value: "nowy@example.com" } });

    await waitFor(() => expect(screen.queryByText("Ten kandydat już jest w bazie")).toBeNull(), {
      timeout: 2000,
    });
    expect(screen.getByRole("button", { name: "Dodaj kandydata" })).toBeInTheDocument();
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
    expect(screen.queryByText("Ten kandydat już jest w bazie")).toBeNull();
  });
});
