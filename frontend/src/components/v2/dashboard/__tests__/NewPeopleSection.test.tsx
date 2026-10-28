import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();
const showInfo = vi.fn();
const router = { push: vi.fn(), replace: vi.fn() };

vi.mock("@/lib/api", () => {
  const client = {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  };
  return { __esModule: true, default: client, api: client };
});
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError, showInfo }),
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
  usePathname: () => window.location.pathname,
  useRouter: () => router,
}));

import { NewPeopleSection, newPersonLabel } from "@/components/v2/dashboard/NewPeopleSection";
import type { NewPersonSetupRow } from "@/lib/api/boardTasks";
import { useAuthStore } from "@/store/auth";

function row(over: Partial<NewPersonSetupRow> = {}): NewPersonSetupRow {
  return {
    user_id: 254,
    name: "Tomasz Nowy",
    email: "t.nowy@example.com",
    since: "2026-10-19T07:12:00Z",
    needs_decision: true,
    missing: [],
    ...over,
  };
}

const TEAM = {
  categories: [
    { id: 1, slug: "infra", name: "Infra & Operations", requests_searching: 3, first: [], second: [] },
    { id: 2, slug: "dev", name: "Development", requests_searching: 5, first: [], second: [] },
  ],
  unassigned: [],
  excluded: [],
  people: [],
  rules: { review_time: "09:00" },
};

function setUser(roles: string[]) {
  useAuthStore.setState({
    user: { id: 11, role: roles[0], roles, name: "Olaf Kierownik" },
    realUser: null,
  } as never);
}

function renderSection(rows: NewPersonSetupRow[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NewPeopleSection rows={rows} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/dashboard");
  get.mockImplementation((url: string) => {
    if (url === "/api/competence-team") return Promise.resolve({ data: TEAM });
    if (url === "/api/people-setup/options")
      return Promise.resolve({
        data: { manager_enabled: true, managers: [{ id: 11, name: "Olaf Kierownik" }, { id: 12, name: "Inna Kierowniczka" }] },
      });
    return Promise.reject(new Error(`unexpected GET ${url}`));
  });
  post.mockResolvedValue({ data: { ok: true } });
});

describe("newPersonLabel", () => {
  it("mówi, czego brakuje", () => {
    expect(newPersonLabel(row())).toBe("Nowe konto · od 19.10");
    expect(newPersonLabel(row({ needs_decision: false, missing: ["categories"] }))).toBe("Rekruter bez kategorii");
    expect(newPersonLabel(row({ needs_decision: false, missing: ["manager"] }))).toBe("Rekruter bez przełożonego");
    expect(newPersonLabel(row({ needs_decision: false, missing: ["categories", "manager"] }))).toBe(
      "Rekruter bez kategorii i przełożonego",
    );
  });
});

describe("NewPeopleSection", () => {
  it("bez osób nic nie pokazuje", () => {
    setUser(["head_of_recruitment"]);
    const { container } = renderSection([]);
    expect(container).toBeEmptyDOMElement();
  });

  it("Head of Recruitment robi rekrutera z kategorią i sobą jako przełożonym", async () => {
    setUser(["head_of_recruitment"]);
    renderSection([row()]);
    await userEvent.click(screen.getByRole("button", { name: "Zdecyduj" }));
    const dialog = await screen.findByRole("dialog");
    // Delivery Leada i inne role nadaje admin.
    expect(within(dialog).getByRole("button", { name: /Delivery Lead/ })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Zapisz" })).toBeDisabled();

    await userEvent.click(within(dialog).getByRole("button", { name: /^Rekruter/ }));
    const first = await within(dialog).findByRole("group", { name: "1. priorytet" });
    await userEvent.click(within(first).getByRole("button", { name: /Development/ }));
    const second = within(dialog).getByRole("group", { name: "2. priorytet" });
    await userEvent.click(within(second).getByRole("button", { name: /Infra/ }));
    await waitFor(() => expect(within(dialog).getByLabelText("Przełożony")).toHaveValue("11"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/people-setup/254", {
        decision: "recruiter",
        first_category_id: 2,
        second_category_ids: [1],
        manager_user_id: 11,
      }),
    );
    expect(showSuccess).toHaveBeenCalledWith("Zapisano: Tomasz Nowy jest rekruterem.");
  });

  it("„Zostaje Konsultantem” zapisuje samą decyzję", async () => {
    setUser(["head_of_recruitment"]);
    renderSection([row()]);
    await userEvent.click(screen.getByRole("button", { name: "Zdecyduj" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /Zostaje Konsultantem/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Zostaw jako Konsultanta" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/people-setup/254", { decision: "employee" }));
  });

  it("„Uzupełnij” pyta tylko o to, czego brakuje", async () => {
    setUser(["admin"]);
    renderSection([row({ user_id: 101, name: "Rekruterka Bez", needs_decision: false, missing: ["categories"] })]);
    await userEvent.click(screen.getByRole("button", { name: "Uzupełnij" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByText("Kim jest ta osoba w NEXUSIE?")).not.toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Przełożony")).not.toBeInTheDocument();
    const first = await within(dialog).findByRole("group", { name: "1. priorytet" });
    await userEvent.click(within(first).getByRole("button", { name: /Infra/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/people-setup/101", {
        decision: "recruiter",
        first_category_id: 1,
        second_category_ids: [],
        manager_user_id: null,
      }),
    );
  });

  it("link z maila „Zostaw jako Konsultanta” otwiera okno z zaznaczonym wariantem i czyści adres", async () => {
    setUser(["head_of_recruitment"]);
    window.history.replaceState(null, "", "/dashboard?nowa-osoba=254&zostaw=1#czeka-na-ciebie");
    renderSection([row()]);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: /Zostaje Konsultantem/ })).toHaveAttribute("aria-pressed", "true");
    expect(post).not.toHaveBeenCalled();
    await waitFor(() => expect(window.location.search).toBe(""));
    expect(window.location.hash).toBe("#czeka-na-ciebie");
  });

  it("link do osoby, którą ktoś już ustawił, mówi o tym zamiast otwierać okno", async () => {
    setUser(["head_of_recruitment"]);
    window.history.replaceState(null, "", "/dashboard?nowa-osoba=999");
    renderSection([row()]);
    await waitFor(() => expect(showInfo).toHaveBeenCalledWith("Tę osobę ktoś już ustawił."));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
