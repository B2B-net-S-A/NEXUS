import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ClientPlaybookForm } from "@/components/client-playbook/ClientPlaybookForm";
import {
  makeClientPlaybook,
  makePlaybookEvent,
} from "@/test/fixtures/client-playbook";

/**
 * Formularz karty klienta — jeden komponent w dwóch miejscach (edytor reguł
 * CV, profil klienta).
 *
 * Kontrakty, które łatwo cofnąć „przy okazji":
 *  * PUT wysyła KOMPLET pól (pełna podmiana po stronie serwera) — liczby jako
 *    int, puste jako null, dokumenty bez niepełnych wierszy;
 *  * po zapisie invaliduje kartę, listę w Pomocy i historię — inaczej karta
 *    obok formularza pokazywałaby starą wersję;
 *  * awaria odczytu NIE udaje pustej karty;
 *  * off-limit jest tylko do odczytu (źródłem prawdy jest umowa ramowa).
 */

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: mocks.get,
    put: mocks.put,
    post: mocks.post,
    delete: mocks.delete,
  },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
}));

const PLAYBOOK_URL = "/api/clients/5/playbook";
const HISTORY_URL = "/api/clients/5/playbook/history";
const SLA_LABEL = "SLA: dni robocze na pierwszego kandydata";

const PAYLOAD_KEYS = [
  "sla_business_days",
  "sla_min_candidates",
  "cv_limit_per_process",
  "hold_hours",
  "multi_project_cooldown_days",
  "rate_policy",
  "about_for_candidate",
  "priority_rules",
  "process_rules_md",
  "onboarding_md",
  "documents",
];

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderForm(onSaved = vi.fn(), queryClient = makeQueryClient()) {
  render(
    <QueryClientProvider client={queryClient}>
      <ClientPlaybookForm clientId={5} onSaved={onSaved} />
    </QueryClientProvider>,
  );
  return { onSaved, queryClient };
}

describe("ClientPlaybookForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockImplementation(async (url: string) => {
      if (url === PLAYBOOK_URL) return { data: makeClientPlaybook({ client_id: 5 }) };
      if (url === HISTORY_URL) return { data: [makePlaybookEvent()] };
      throw new Error(`unexpected GET ${url}`);
    });
    mocks.put.mockImplementation(async (_url: string, body: Record<string, unknown>) => ({
      data: makeClientPlaybook({ ...(body as object), client_id: 5, version: 4 }),
    }));
  });

  it("wysyła PUT z kompletem pól: liczby jako int, puste jako null, dokumenty bez niepełnych wierszy", async () => {
    const { onSaved } = renderForm();
    const sla = await screen.findByLabelText(SLA_LABEL);

    fireEvent.change(sla, { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Blokada kandydata (godziny)"), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj dokument" }));
    fireEvent.change(screen.getByLabelText("Dokument 2: nazwa"), {
      target: { value: "Tylko nazwa, bez linku" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Zapisz kartę" }));

    await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
    const [url, body] = mocks.put.mock.calls[0] as [string, Record<string, unknown>];
    expect(url).toBe(PLAYBOOK_URL);
    expect(Object.keys(body).sort()).toEqual([...PAYLOAD_KEYS].sort());
    expect(body).toMatchObject({
      sla_business_days: 7,
      sla_min_candidates: 3,
      cv_limit_per_process: 4,
      hold_hours: null,
      multi_project_cooldown_days: 90,
      rate_policy: "Maks. 180 PLN/h B2B, bez negocjacji po wysyłce CV.",
      priority_rules: "Kandydaci z bankowością w pierwszej kolejności",
      process_rules_md: "## Etapy\n1. Screening HR\n2. Zadanie techniczne",
    });
    // Wiersz bez linku odpada; pełny wiersz z fixture zostaje.
    expect(body.documents).toEqual([
      { name: "NDA klienta", url: "https://b2bnetsa.sharepoint.com/nda" },
    ]);

    expect(await screen.findByText("Zapisano kartę (wersja 4).")).toBeInTheDocument();
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ version: 4 }));
    expect(screen.getByText(/Karta klienta · wersja 4/)).toBeInTheDocument();
    // Dwa podglądy markdown + historia renderują się przy każdej zmianie pola;
    // pod obciążeniem (pełny pakiet) domyślne 5 s bywa za mało.
  }, 15_000);

  it("po zapisie invaliduje kartę, listę ustawień i historię", async () => {
    const queryClient = makeQueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    renderForm(vi.fn(), queryClient);
    await screen.findByLabelText(SLA_LABEL);

    fireEvent.click(screen.getByRole("button", { name: "Zapisz kartę" }));
    await screen.findByText("Zapisano kartę (wersja 4).");

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["client-playbook", 5] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["settings-client-playbooks"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["client-playbook-history", 5] });
  });

  it("błąd zapisu pokazuje komunikat inline i nie czyści formularza", async () => {
    mocks.put.mockRejectedValueOnce(new Error("Za długie"));
    renderForm();
    const sla = await screen.findByLabelText(SLA_LABEL);

    fireEvent.change(sla, { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz kartę" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Za długie");
    expect(screen.getByLabelText(SLA_LABEL)).toHaveValue(7);
    expect(screen.getByText("Niezapisane zmiany karty")).toBeInTheDocument();
    // „Zapisano kartę" bez wersji to etykieta wpisu w HISTORII — komunikat
    // sukcesu zapisu niesie numer wersji.
    expect(screen.queryByText(/Zapisano kartę \(wersja/)).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("awaria odczytu nie udaje pustej karty", async () => {
    mocks.get.mockImplementation(async (url: string) => {
      if (url === PLAYBOOK_URL) throw new Error("network down");
      if (url === HISTORY_URL) return { data: [] };
      throw new Error(`unexpected GET ${url}`);
    });
    renderForm();

    expect(
      await screen.findByText("Nie udało się wczytać karty klienta."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zapisz kartę" })).not.toBeInTheDocument();
    expect(screen.queryByText("Brak karty")).not.toBeInTheDocument();
  });

  it("podgląd markdown renderuje się na żywo", async () => {
    renderForm();
    const field = await screen.findByLabelText("Zasady procesu rekrutacji (Markdown)");
    expect(screen.getByRole("heading", { name: "Etapy" })).toBeInTheDocument();

    fireEvent.change(field, { target: { value: "## Nowy etap" } });

    expect(await screen.findByRole("heading", { name: "Nowy etap" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Etapy" })).not.toBeInTheDocument();
  });

  it("historia pokazuje ostatnie wpisy z diffem", async () => {
    renderForm();
    const history = await screen.findByTestId("playbook-history");

    expect(await within(history).findByText("Zapisano kartę")).toBeInTheDocument();
    expect(within(history).getByText("v3")).toBeInTheDocument();
    expect(within(history).getByText(/Artur/)).toBeInTheDocument();
    expect(within(history).getByText(/SLA: dni robocze na pierwszego kandydata/)).toBeInTheDocument();
    expect(within(history).getByText("3")).toBeInTheDocument();
    expect(within(history).getByText(/5$/)).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith(HISTORY_URL, { params: { limit: 10 } });
  });

  it("off-limit jest tylko do odczytu", async () => {
    renderForm();
    await screen.findByLabelText(SLA_LABEL);

    expect(screen.getByTestId("playbook-off-limits")).toHaveTextContent("12 mies. · Cały bank");
    expect(screen.queryByLabelText("Off-limit (z warunków umowy)")).not.toBeInTheDocument();
    // Etykieta jest, ale jako opis pola do odczytu, nie <label> kontrolki.
    expect(screen.getByText("Off-limit (z warunków umowy)")).toBeInTheDocument();
  });
});
