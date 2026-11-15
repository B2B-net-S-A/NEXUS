import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const patch = vi.fn();
const post = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    patch: (...a: unknown[]) => patch(...a),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast, showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/compliance",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { ComplianceScreen, DISABLED_NOTICE } from "@/components/compliance/ComplianceScreen";
import type { ChangeDetail, LawChangeListItem, RunList } from "@/lib/api/compliance";
import { useAuthStore } from "@/store/auth";

// Fikcyjne zmiany i liczby — repo jest publiczne.
function change(overrides: Partial<LawChangeListItem> = {}): LawChangeListItem {
  return {
    id: 1,
    title: "Przykładowa zmiana w ustawie o VAT",
    summary: ["Punkt pierwszy skrótu."],
    roles: ["accounting"],
    urgency: "now",
    stage: "journal",
    effective_on: "2099-01-01",
    deadline: null,
    legal_ref: "DU/2099/1",
    status: "new",
    decision_note: null,
    decided_at: null,
    created_at: "2026-11-10T08:00:00Z",
    updated_at: "2026-11-10T08:00:00Z",
    probes: [{ key: "probe_a", value: 7, text: "7 przykładowych faktur", link: "/accounting", computed_at: null }],
    tasks: { open: 1, done: 0 },
    ...overrides,
  };
}

function detail(row: LawChangeListItem): ChangeDetail {
  const { probes, tasks: _tasks, ...rest } = row;
  return {
    enabled: true,
    change: { ...rest, decided_by: null },
    items: [
      {
        id: 11,
        source: "sejm",
        klass: "official",
        gate: "verified",
        title: "Akt w Dzienniku Ustaw",
        url: "https://example.gov.pl/akt",
        published: "2026-11-09",
        act_ref: "DU/2099/1",
        print_no: null,
        stage: null,
        quote: null,
        official: {},
      },
      {
        id: 12,
        source: "x",
        klass: "practice",
        gate: "unverified",
        title: "Wpis doradcy",
        url: "javascript:alert(1)",
        published: "2026-11-09",
        act_ref: null,
        print_no: null,
        stage: null,
        quote: null,
        official: {},
      },
    ],
    tasks: [
      {
        id: 21,
        text: "Sprawdzić numerację",
        role: "accounting",
        source: "bot",
        assignee: null,
        due_on: null,
        done: false,
        done_at: null,
      },
    ],
    events: [],
    probes,
  };
}

const RUNS: RunList = { enabled: true, configured: { collect: true, analyze: true }, runs: [] };

function route(changes: LawChangeListItem[] | "disabled" | "fail") {
  get.mockImplementation(async (url: string) => {
    if (url === "/api/compliance/changes") {
      if (changes === "fail") throw Object.assign(new Error("boom"), { response: { status: 500 } });
      if (changes === "disabled") return { data: { enabled: false, changes: [] } };
      return { data: { enabled: true, changes } };
    }
    if (url === "/api/compliance/runs") return { data: RUNS };
    const match = /^\/api\/compliance\/changes\/(\d+)$/.exec(url);
    if (match && Array.isArray(changes)) {
      const row = changes.find((c) => c.id === Number(match[1]));
      if (row) return { data: detail(row) };
    }
    throw new Error(`nieoczekiwane ${url}`);
  });
}

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ComplianceScreen />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  patch.mockReset();
  post.mockReset();
  showToast.mockReset();
  window.history.replaceState(null, "", "/compliance");
  useAuthStore.setState({
    user: { id: 5, role: "finance", roles: ["finance"] },
    realUser: null,
    hydrated: true,
  } as never);
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("Przepisy — ekran", () => {
  it("lista z API, szczegół z sondą „U nas”, źródła po klasach i bez linku spoza http(s)", async () => {
    route([change(), change({ id: 2, title: "Druga zmiana", urgency: "watch", probes: [], tasks: { open: 0, done: 0 } })]);
    renderScreen();

    const list = await screen.findByRole("list", { name: "Zmiany w prawie" });
    expect(within(list).getByText("Przykładowa zmiana w ustawie o VAT")).toBeInTheDocument();
    expect(within(list).getByText("Druga zmiana")).toBeInTheDocument();

    const card = await screen.findByRole("article", { name: "Przykładowa zmiana w ustawie o VAT" });
    expect(within(card).getByText("Co to znaczy dla nas (dane z NEXUSA)")).toBeInTheDocument();
    expect(within(card).getByText("7 przykładowych faktur")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: /Akt w Dzienniku Ustaw/ })).toHaveAttribute(
      "href",
      "https://example.gov.pl/akt",
    );
    expect(within(card).getByText("Urzędowe")).toBeInTheDocument();
    expect(within(card).getByText("Praktyka")).toBeInTheDocument();
    expect(within(card).queryByRole("link", { name: /Wpis doradcy/ })).toBeNull();
    expect(within(card).getByText("Sprawdzić numerację")).toBeInTheDocument();
  });

  it("soczewka roli pyta API z `role` i zapisuje ją w adresie", async () => {
    route([change()]);
    renderScreen();
    await screen.findByRole("list", { name: "Zmiany w prawie" });
    await userEvent.click(screen.getByRole("button", { name: "Kadry i płace" }));
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith("/api/compliance/changes", { params: { role: "payroll" } }),
    );
    expect(window.location.search).toContain("lens=payroll");
  });

  it("awaria listy to błąd z ponowieniem, nie pusta lista", async () => {
    route("fail");
    renderScreen();
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się pobrać danych");
    expect(screen.getByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
    expect(screen.queryByText("Brak zmian dla tej roli.")).toBeNull();
  });

  it("pusta lista po sukcesie mówi „Brak zmian dla tej roli.”", async () => {
    route([]);
    renderScreen();
    expect(await screen.findByText("Brak zmian dla tej roli.")).toBeInTheDocument();
  });

  it("wyłączony radar: spokojny komunikat o fladze", async () => {
    route("disabled");
    renderScreen();
    expect(await screen.findByText(DISABLED_NOTICE)).toBeInTheDocument();
    expect(screen.queryByText("Brak zmian dla tej roli.")).toBeNull();
  });

  it("„Nie dotyczy” wymaga powodu i wysyła go w PATCH", async () => {
    route([change()]);
    patch.mockResolvedValue({ data: { enabled: true, change: change({ status: "not_applicable" }) } });
    renderScreen();
    const card = await screen.findByRole("article", { name: "Przykładowa zmiana w ustawie o VAT" });

    await userEvent.click(within(card).getByRole("button", { name: "Nie dotyczy (z powodem)" }));
    const dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Zapisz „Nie dotyczy”" });
    expect(confirm).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText("Powód"), "   ");
    expect(confirm).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText("Powód"), "Nie mamy takich umów");
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);

    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith("/api/compliance/changes/1", {
        status: "not_applicable",
        note: "Nie mamy takich umów",
      }),
    );
  });

  it("„Dotyczy nas” przestawia zmianę na „W toku”", async () => {
    route([change()]);
    patch.mockResolvedValue({ data: { enabled: true, change: change({ status: "in_progress" }) } });
    renderScreen();
    const card = await screen.findByRole("article", { name: "Przykładowa zmiana w ustawie o VAT" });
    await userEvent.click(within(card).getByRole("button", { name: "Dotyczy nas" }));
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith("/api/compliance/changes/1", { status: "in_progress", note: undefined }),
    );
  });

  it("bez roli i uprawnienia: komunikat o braku dostępu, bez zapytań", async () => {
    useAuthStore.setState({
      user: { id: 6, role: "recruiter", roles: ["recruiter"] },
      realUser: null,
      hydrated: true,
    } as never);
    route([change()]);
    renderScreen();
    expect(screen.getByText("Brak uprawnień")).toBeInTheDocument();
    expect(get).not.toHaveBeenCalled();
  });

  it("403 z API pokazuje brak uprawnień, nie pustą listę", async () => {
    get.mockImplementation(async (url: string) => {
      if (url === "/api/compliance/runs") return { data: RUNS };
      throw Object.assign(new Error("403"), { response: { status: 403 } });
    });
    renderScreen();
    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.queryByText("Brak zmian dla tej roli.")).toBeNull();
  });
});
