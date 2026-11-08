/**
 * „Dodaj do słownika” w kolejce nazw z rozmów: kategoria jest obowiązkowa jak
 * w „Słowniku umiejętności” (etap 2, 06.11.2026), lista kategorii przychodzi
 * z kolejki, a wybrana idzie do serwera. Dane zmyślone.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), showToast: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
    put: vi.fn(),
    patch: vi.fn(),
  },
  skillsAdminApi: { list: vi.fn() },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.showToast, showError: vi.fn() }),
}));

import { SkillReviewPanel } from "@/components/care/SkillReviewPanel";
import type { SkillReviewRow } from "@/lib/api/care";

const row: SkillReviewRow = {
  id: 5,
  name: "Platforma Testowa",
  status: "open",
  occurrences: 3,
  skill: null,
  reported_by: { id: 1, name: "Opiekun Testowy" },
  suggestions: [],
  created_at: "2026-11-02T10:00:00Z",
  resolved_at: null,
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SkillReviewPanel />
    </QueryClientProvider>,
  );
}

async function openCreateDialog() {
  const user = userEvent.setup();
  renderPanel();
  await user.click(await screen.findByRole("button", { name: "Dodaj do słownika" }));
  return { user, dialog: await screen.findByRole("dialog") };
}

describe("SkillReviewPanel · Dodaj do słownika", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.post.mockReset();
    mocks.showToast.mockReset();
    mocks.get.mockResolvedValue({
      data: { items: [row], can_curate: true, categories: ["backend", "practice", "tools"] },
    });
  });

  it("bez kategorii „Dodaj” jest nieaktywne i nie ma „Bez kategorii”", async () => {
    const { dialog } = await openCreateDialog();
    const select = within(dialog).getByRole("combobox", { name: "Kategoria" });
    expect(select).toHaveValue("");
    expect(within(select).queryByRole("option", { name: "Bez kategorii" })).toBeNull();
    expect(within(select).getByRole("option", { name: "Wybierz kategorię…" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Dodaj" })).toBeDisabled();
  });

  it("lista kategorii przychodzi z kolejki, z polskimi nazwami", async () => {
    const { dialog } = await openCreateDialog();
    const select = within(dialog).getByRole("combobox", { name: "Kategoria" });
    const labels = within(select)
      .getAllByRole("option")
      .map((option) => option.textContent);
    expect(labels).toEqual(["Wybierz kategorię…", "Backend", "Praktyki", "Narzędzia"]);
  });

  it("wysyła wybraną kategorię", async () => {
    mocks.post.mockResolvedValue({ data: { id: 5, status: "created", skill_id: 77 } });
    const { user, dialog } = await openCreateDialog();
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Kategoria" }), "tools");
    const add = within(dialog).getByRole("button", { name: "Dodaj" });
    expect(add).toBeEnabled();
    await user.click(add);
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/care/skill-review/5/create", {
        canonical_name: "Platforma Testowa",
        category: "tools",
      }),
    );
    expect(mocks.showToast).toHaveBeenCalledWith("Umiejętność dodana", "success");
  });

  it("odmowa serwera zostaje w oknie jako komunikat", async () => {
    mocks.post.mockRejectedValue({
      isAxiosError: true,
      response: { status: 422, data: { detail: "Nieznana kategoria „tools”." } },
    });
    const { user, dialog } = await openCreateDialog();
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Kategoria" }), "tools");
    await user.click(within(dialog).getByRole("button", { name: "Dodaj" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Nieznana kategoria");
  });
});
