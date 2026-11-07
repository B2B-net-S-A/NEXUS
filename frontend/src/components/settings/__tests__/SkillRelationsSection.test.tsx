import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SkillRelationsSection } from "../SkillRelationsSection";

const api = vi.hoisted(() => ({ relations: vi.fn(), withdrawRelation: vi.fn() }));
const confirm = vi.hoisted(() => ({ askConfirm: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, skillsAdminApi: { ...actual.skillsAdminApi, ...api } };
});
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: confirm.askConfirm, confirmDialog: null }),
}));

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SkillRelationsSection />
    </QueryClientProvider>,
  );
}

const relation = {
  id: 7,
  from: { id: 2, name: "Spring Boot", category: "backend" },
  to: { id: 1, name: "Java", category: "language" },
  kind: "implies" as const,
  status: "accepted" as const,
  source: "glossary" as const,
  support: 3943,
  share: 0.977,
  reason: "Spring Boot jest oparty na Javie.",
  sure: false,
  curated_by: "auto: model + dane",
};

describe("SkillRelationsSection — mapa wiedzy IT (07.11.2026)", () => {
  beforeEach(() => {
    api.relations.mockResolvedValue({
      items: [relation],
      total: 1,
      totals: { proposed: 0, accepted: 536, rejected: 3, sure: 0 },
    });
    api.withdrawRelation.mockResolvedValue({ id: 7, status: "rejected" });
    confirm.askConfirm.mockResolvedValue(true);
  });

  it("pokazuje powiązanie z rodzajem, poparciem w danych i uzasadnieniem", async () => {
    renderSection();
    expect(await screen.findByText("Spring Boot ⇒ Java")).toBeInTheDocument();
    expect(screen.getByText("wynika z")).toBeInTheDocument();
    expect(screen.getByText(/98% z 3\s?943 profili · Spring Boot jest oparty na Javie\./)).toBeInTheDocument();
    expect(screen.getByText(/działa 536\b/)).toBeInTheDocument();
  });

  it("„Wycofaj” pyta o potwierdzenie i wycofuje", async () => {
    const user = userEvent.setup();
    renderSection();
    await user.click(await screen.findByRole("button", { name: "Wycofaj" }));
    expect(confirm.askConfirm).toHaveBeenCalled();
    expect(api.withdrawRelation).toHaveBeenCalledWith(7);
  });

  it("filtr rodzaju idzie do serwera", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByText("Spring Boot ⇒ Java");
    await user.click(screen.getByRole("radio", { name: "Zamienniki" }));
    expect(api.relations).toHaveBeenLastCalledWith(
      expect.objectContaining({ kind: "alternative", status: "accepted" }),
    );
  });
});
