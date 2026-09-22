import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const listMock = vi.fn();
const updateMock = vi.fn();

vi.mock("@/lib/api", () => ({
  savedSearchesApi: {
    list: (...a: unknown[]) => listMock(...a),
    update: (...a: unknown[]) => updateMock(...a),
    create: vi.fn(),
    delete: vi.fn(),
    markViewed: vi.fn(),
  },
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (sel: (s: { user: { id: number } }) => unknown) =>
    sel({ user: { id: 7 } }),
}));

import { SavedSearchesMenu } from "../SavedSearchesMenu";
import { semanticsReapproval } from "@/lib/saved-search-reapproval";

const migrated = {
  id: 11,
  user_id: 7,
  name: "Gdańsk A_B",
  entity: "candidates",
  shared: false,
  description: null,
  notify_new_matches: false,
  requires_reapproval: true,
  unseen_count: 0,
  filters: {
    version: 3,
    semantics_version: 2,
    origin: "candidates_list",
    qs: "loc=A_B&sv=2",
    request: { semantics_version: 2, location_cities: ["A_B"] },
    legacy: { version: 2, qs: "loc=A_B", api: { location: "A_B" } },
    migration: {
      outcome: "different",
      alert_was_on: true,
      diff: {
        legacy_total: 12,
        unified_total: 9,
        only_legacy: 3,
        only_unified: 0,
        rules: ["location_wildcards"],
      },
    },
  },
};

const retiredRate = {
  ...migrated,
  id: 12,
  name: "Stary zapis ze stawką",
  filters: { version: 2, qs: "q=java", api: { q: "java" } },
};

function renderMenu() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SavedSearchesMenu currentQs="" onApply={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe("SavedSearchesMenu — zmiana zasad wyszukiwania", () => {
  beforeEach(() => {
    listMock.mockReset();
    updateMock.mockReset();
    listMock.mockResolvedValue({ data: [migrated, retiredRate] });
    updateMock.mockResolvedValue({ data: { ...migrated, requires_reapproval: false } });
  });

  it("pokazuje własny komunikat z liczbami i przyczyną, nie tekst o stawkach", async () => {
    const user = userEvent.setup();
    renderMenu();
    await user.click(screen.getByRole("button", { name: /Zapisane/ }));
    await user.click(await screen.findByRole("button", { name: "Sprawdź zmianę" }));

    const panel = screen.getByRole("group", {
      name: "Zmiana zasad wyszukiwania: Gdańsk A_B",
    });
    expect(within(panel).getByText("Zmieniły się zasady wyszukiwania")).toBeTruthy();
    expect(panel.textContent).toContain("dotąd 12, po zmianie 9");
    expect(panel.textContent).toContain("traktowane dosłownie");
    expect(panel.textContent).toContain("Alert jest wstrzymany");
    expect(panel.textContent).not.toContain("miesięczn");
    // zapis po wycofaniu stawek miesięcznych zostaje przy dotychczasowej plakietce
    expect(screen.getByText("Ponownie zatwierdź")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Sprawdź zmianę" })).toHaveLength(1);
  });

  it("„Zatwierdź nowe wyniki” i „Zostaw po staremu” wysyłają właściwy wybór", async () => {
    const user = userEvent.setup();
    renderMenu();
    await user.click(screen.getByRole("button", { name: /Zapisane/ }));
    await user.click(await screen.findByRole("button", { name: "Sprawdź zmianę" }));
    await user.click(screen.getByRole("button", { name: "Zostaw po staremu" }));
    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith(11, {
        confirm_reapproval: true,
        reapproval_choice: "keep_legacy",
      }),
    );

    await user.click(await screen.findByRole("button", { name: "Sprawdź zmianę" }));
    await user.click(screen.getByRole("button", { name: "Zatwierdź nowe wyniki" }));
    await waitFor(() =>
      expect(updateMock).toHaveBeenLastCalledWith(11, {
        confirm_reapproval: true,
        reapproval_choice: "accept",
      }),
    );
  });

  it("dzwonek przy wstrzymanym zapisie otwiera decyzję zamiast przebudowywać filtry", async () => {
    const user = userEvent.setup();
    renderMenu();
    await user.click(screen.getByRole("button", { name: /Zapisane/ }));
    await user.click(
      await screen.findByRole("button", { name: "Przełącz alert dla Gdańsk A_B" }),
    );
    expect(updateMock).not.toHaveBeenCalled();
    expect(screen.getByText("Zmieniły się zasady wyszukiwania")).toBeTruthy();
  });
});

describe("semanticsReapproval", () => {
  it("czyta liczby i tłumaczy kody; nieznany kod → opis ogólny", () => {
    const r = semanticsReapproval({
      migration: { diff: { legacy_total: 1, unified_total: 2, rules: ["tags_whole_match", "cos_nowego"] } },
    });
    expect(r?.legacyTotal).toBe(1);
    expect(r?.ruleLabels).toHaveLength(2);
    expect(r?.ruleLabels[0]).toContain("tag musi pasować w całości");
  });

  it("zwraca null dla zapisu bez migracji i po akceptacji", () => {
    expect(semanticsReapproval({ qs: "q=x" })).toBeNull();
    expect(
      semanticsReapproval({ migration: { reapproved_at: "2026-09-21T10:00:00Z" } }),
    ).toBeNull();
  });
});
