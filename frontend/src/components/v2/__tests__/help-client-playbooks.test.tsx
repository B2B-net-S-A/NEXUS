import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HelpClientPlaybooksSection } from "@/components/v2/pages/HelpClientPlaybooksSection";
import { makeClientPlaybook } from "@/test/fixtures/client-playbook";
import { makeCvRule } from "@/test/fixtures/cv-rule";

/**
 * Pomoc → Klienci — procedura per klient generowana z karty.
 *
 * Kontrakty, które łatwo cofnąć „przy okazji":
 *  * lista sortuje po nazwie (nie po kolejności z API) i auto-wybiera pierwszego;
 *  * `?client=<id>` (link „Pełna karta klienta →" z rekrutacji) wygrywa
 *    z auto-wyborem — także zanim lista dojedzie;
 *  * lista zasiewa cache kart, więc prawy panel NIE robi GET per klient;
 *  * awaria pobrania to alert z ponowieniem, nigdy pustka.
 */

const mocks = vi.hoisted(() => ({
  user: null as Record<string, unknown> | null,
  search: "",
  get: vi.fn(),
  put: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(mocks.search),
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

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: mocks.user, realUser: null, hydrated: true }),
  getUserRoles: (user: { role?: string; roles?: string[] } | null) =>
    user ? Array.from(new Set([user.role, ...(user.roles ?? [])])) : [],
  hasRole: (
    user: { role?: string; roles?: string[] } | null,
    ...roles: string[]
  ) =>
    !!user &&
    roles.some((role) =>
      new Set([user.role, ...(user.roles ?? [])]).has(role),
    ),
}));

const RECRUITER_USER = { id: 8, role: "recruiter", roles: ["recruiter"] };
const OVERVIEW_URL = "/api/settings/client-playbooks";

// PKO celowo PRZED Nordeą — lista ma sortować po nazwie, nie po API.
const ITEMS = [
  makeClientPlaybook({ client_id: 2, client_name: "PKO Bank Polski", version: 1 }),
  makeClientPlaybook(),
];

function routeDefault(items = ITEMS) {
  mocks.get.mockImplementation(async (url: string) => {
    if (url === OVERVIEW_URL) return { data: { items } };
    if (url === "/api/clients/1/cv-rule") return { data: makeCvRule() };
    if (url === "/api/clients/2/cv-rule")
      return { data: makeCvRule({ client_id: 2, client_name: "PKO Bank Polski" }) };
    // Gdyby zasiew cache nie zadziałał, test ma paść na asercji, nie na
    // „unexpected GET" — dlatego karty per klient TEŻ są zmockowane.
    if (url === "/api/clients/1/playbook") return { data: ITEMS[1] };
    if (url === "/api/clients/2/playbook") return { data: ITEMS[0] };
    throw new Error(`unexpected GET ${url}`);
  });
}

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <HelpClientPlaybooksSection />
    </QueryClientProvider>,
  );
}

describe("HelpClientPlaybooksSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.user = RECRUITER_USER;
    mocks.search = "";
    routeDefault();
  });

  it("lista klientów z kartą, auto-wybór pierwszego alfabetycznie, prawy panel z pełną kartą", async () => {
    renderSection();

    const nordea = await screen.findByRole("button", { name: /Nordea/ });
    expect(nordea).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: /PKO/ })).not.toHaveAttribute("aria-current");
    expect(await screen.findByText("Karta klienta — Nordea Bank Abp")).toBeInTheDocument();
    expect(screen.getByText("2 z 2")).toBeInTheDocument();
    // Rekruter czyta, ale nie edytuje — link do profilu klienta tylko z capability.
    expect(screen.queryByRole("link", { name: "Edytuj kartę" })).not.toBeInTheDocument();
  });

  it("kliknięcie innego klienta przełącza panel", async () => {
    renderSection();
    await screen.findByText("Karta klienta — Nordea Bank Abp");

    fireEvent.click(screen.getByRole("button", { name: /PKO Bank Polski/ }));

    expect(await screen.findByText("Karta klienta — PKO Bank Polski")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /PKO/ })).toHaveAttribute("aria-current", "true");
    expect(screen.queryByText("Karta klienta — Nordea Bank Abp")).not.toBeInTheDocument();
  });

  it("szukajka filtruje po nazwie klienta po debounce", async () => {
    renderSection();
    await screen.findByRole("button", { name: /Nordea/ });

    fireEvent.change(screen.getByLabelText("Szukaj klienta"), { target: { value: "pko" } });

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /Nordea/ })).not.toBeInTheDocument(),
    );
    // Odfiltrowany klient traci zaznaczenie — wybór przeskakuje na pierwszy
    // widoczny (efekt biegnie PO renderze listy, stąd waitFor).
    expect(await screen.findByText("Karta klienta — PKO Bank Polski")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /PKO/ })).toHaveAttribute("aria-current", "true"),
    );
    expect(screen.getByText("1 z 2")).toBeInTheDocument();
  });

  it("pusta lista to EmptyState „Żaden klient nie ma jeszcze karty”", async () => {
    routeDefault([]);
    renderSection();

    expect(await screen.findByText("Żaden klient nie ma jeszcze karty")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("awaria pobrania listy to alert z ponowieniem, nie pustka", async () => {
    let failuresLeft = 1;
    mocks.get.mockImplementation(async (url: string) => {
      if (url === OVERVIEW_URL) {
        if (failuresLeft > 0) {
          failuresLeft -= 1;
          throw new Error("network down");
        }
        return { data: { items: ITEMS } };
      }
      if (url.endsWith("/cv-rule")) return { data: makeCvRule() };
      throw new Error(`unexpected GET ${url}`);
    });
    renderSection();

    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się pobrać danych");
    expect(screen.queryByText(/Żaden klient/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Spróbuj ponownie/ }));
    expect(await screen.findByRole("button", { name: /Nordea/ })).toBeInTheDocument();
  });

  it("prawy panel nie robi GET per klient, gdy lista zasiała cache", async () => {
    renderSection();
    await screen.findByText("Karta klienta — Nordea Bank Abp");
    fireEvent.click(screen.getByRole("button", { name: /PKO Bank Polski/ }));
    await screen.findByText("Karta klienta — PKO Bank Polski");

    const playbookGets = mocks.get.mock.calls.filter(([url]) =>
      String(url).endsWith("/playbook"),
    );
    expect(playbookGets).toEqual([]);
    expect(mocks.get).toHaveBeenCalledWith(OVERVIEW_URL);
  });

  it("?client=2 zaznacza wskazanego klienta zamiast pierwszego", async () => {
    mocks.search = "tab=clients&client=2";
    renderSection();

    const pko = await screen.findByRole("button", { name: /PKO/ });
    expect(pko).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: /Nordea/ })).not.toHaveAttribute("aria-current");
    expect(await screen.findByText("Karta klienta — PKO Bank Polski")).toBeInTheDocument();
    expect(screen.queryByText("Karta klienta — Nordea Bank Abp")).not.toBeInTheDocument();
  });
});
