import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SkillDictionaryTab } from "../SkillDictionaryTab";

const api = vi.hoisted(() => ({ list: vi.fn(), unmatchedTerms: vi.fn() }));

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
    api.list.mockResolvedValue({
      total: 1,
      items: [{ id: 1, name: "Kubernetes", category: null, aliases: ["k8s"] }],
    });
    api.unmatchedTerms.mockResolvedValue([]);
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
});
