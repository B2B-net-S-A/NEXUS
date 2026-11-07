import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SkillDictionaryTab } from "../SkillDictionaryTab";

const api = vi.hoisted(() => ({
  list: vi.fn(),
  unmatchedTerms: vi.fn(),
  proposals: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  setAliasInText: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, skillsAdminApi: { ...actual.skillsAdminApi, ...api } };
});
vi.mock("@/components/settings/PlainTermsSection", () => ({
  PlainTermsSection: () => <div>Lista haseł po ludzku</div>,
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SkillDictionaryTab />
    </QueryClientProvider>,
  );
}

describe("SkillDictionaryTab — trzy listy w zakładkach (20.10.2026)", () => {
  beforeEach(() => {
    api.list.mockImplementation((params: { kind?: string } = {}) =>
      Promise.resolve(
        params.kind === "roles"
          ? {
              total: 1,
              items: [
                { id: 2, name: "Team Lead", category: "role_management", is_role: true, aliases: [] },
              ],
              categories: ["practice", "tools"],
            }
          : {
              total: 1,
              items: [{ id: 1, name: "Kubernetes", category: null, aliases: ["k8s"] }],
              categories: ["practice", "tools"],
            },
      ),
    );
    api.unmatchedTerms.mockResolvedValue([]);
    api.proposals.mockResolvedValue({
      items: [],
      total: 0,
      totals: { open: 7, names: 12, sure: 0, by_decision: {} },
      computed_at: null,
      categories: [],
    });
  });

  it("otwiera słownik; nieznane terminy i „Po ludzku” ładują się dopiero w swojej zakładce", async () => {
    const user = userEvent.setup();
    renderTab();
    expect(await screen.findByText("Kubernetes")).toBeInTheDocument();
    expect(api.unmatchedTerms).not.toHaveBeenCalled();
    expect(screen.queryByText("Lista haseł po ludzku")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Nieznane terminy" }));
    expect(await screen.findByText("Nie ma nieznanych terminów do przejrzenia.")).toBeInTheDocument();
    expect(screen.queryByText("Kubernetes")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Po ludzku" }));
    expect(screen.getByText("Lista haseł po ludzku")).toBeInTheDocument();
  });

  it("zakładka „Propozycje” pokazuje liczbę otwartych propozycji (06.11.2026)", async () => {
    renderTab();
    expect(await screen.findByRole("tab", { name: "Propozycje · 7" })).toBeInTheDocument();
  });

  it("nowe hasło wymaga kategorii (etap 2)", async () => {
    const user = userEvent.setup();
    api.create.mockResolvedValue({ id: 9, canonical_name: "Apache Kafka", mapped_term: null });
    renderTab();
    await screen.findByText("Kubernetes");
    await user.type(screen.getByLabelText("Nazwa umiejętności"), "Apache Kafka");
    const add = screen.getByRole("button", { name: /Dodaj umiejętność/ });
    expect(add).toBeDisabled();
    await user.selectOptions(screen.getByLabelText("Kategoria nowej umiejętności"), "tools");
    await user.click(add);
    expect(api.create).toHaveBeenCalledWith({
      canonical_name: "Apache Kafka",
      category: "tools",
      aliases: [],
    });
  });

  it("role są w osobnej grupie i nie mają „Dodaj alias”", async () => {
    const user = userEvent.setup();
    renderTab();
    await screen.findByText("Kubernetes");
    await user.click(screen.getByRole("radio", { name: "Role" }));
    expect(await screen.findByText("Team Lead")).toBeInTheDocument();
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ kind: "roles" }));
    expect(screen.queryByRole("button", { name: "Dodaj alias" })).not.toBeInTheDocument();
    expect(screen.getByText(/nie przyjmuje nowych aliasów/)).toBeInTheDocument();
  });

  it("„Popraw” zmienia nazwę i kategorię hasła", async () => {
    const user = userEvent.setup();
    api.update.mockResolvedValue({ id: 1, canonical_name: "Kubernetes (K8s)", category: "tools" });
    renderTab();
    await screen.findByText("Kubernetes");
    await user.click(screen.getByRole("button", { name: "Popraw" }));
    const nameField = screen.getByLabelText("Nazwa hasła Kubernetes");
    await user.clear(nameField);
    await user.type(nameField, "Kubernetes (K8s)");
    await user.selectOptions(screen.getByLabelText("Kategoria"), "tools");
    expect(screen.getByText(/zostanie aliasem/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(api.update).toHaveBeenCalledWith(1, {
      canonical_name: "Kubernetes (K8s)",
      category: "tools",
    });
  });

  it("wariant przekreślony nie liczy się w tekście CV, kliknięcie to zmienia (etap 3a)", async () => {
    const user = userEvent.setup();
    api.list.mockResolvedValue({
      total: 1,
      items: [
        {
          id: 5,
          name: "Microsoft Project",
          category: "tools",
          aliases: ["ms project", "project"],
          alias_details: [
            { id: 51, alias: "ms project", in_text: null, counts_in_text: true },
            { id: 52, alias: "project", in_text: null, counts_in_text: false },
          ],
        },
      ],
      categories: ["tools"],
    });
    api.setAliasInText.mockResolvedValue({
      id: 52,
      alias: "project",
      in_text: true,
      counts_in_text: true,
    });
    renderTab();
    const off = await screen.findByRole("button", { name: "project" });
    expect(off).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "ms project" })).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByText(/Przekreślone nie liczą się, gdy QC szuka wymagania w tekście CV/),
    ).toBeInTheDocument();
    await user.click(off);
    expect(api.setAliasInText).toHaveBeenCalledWith(52, true);
  });
});
