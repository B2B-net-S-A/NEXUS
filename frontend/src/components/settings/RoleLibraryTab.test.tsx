/**
 * Biblioteka ról (runda 2, 21.10.2026): najpierw opis do czytania, edycja pod
 * „Edytuj”, źródła i historia w zakładkach. Dane fikcyjne.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { RoleProfileDetail } from "@/lib/api/plainKnowledge";

const ROLE: RoleProfileDetail = vi.hoisted(
  () =>
    ({
      id: 5,
      slug: "tester",
      name: "Tester automatyzujący",
      summary: "Pisze testy, które same sprawdzają aplikację.",
      example: "",
      day_to_day: ["Pisze testy w Selenium", "Pilnuje testów w CI"],
      candidate_questions: ["Jakich narzędzi używacie?"],
      typical_skills: ["Selenium", "Java"],
      sources: [],
      origin: "seed",
      status: "ready",
      stats: { jobs: 3, clients: 2, hires: 1, hired_titles: [] },
      history: [],
    }) as unknown as RoleProfileDetail,
);
const mutate = vi.hoisted(() => vi.fn());

vi.mock("@/components/Toast", () => ({ useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }) }));
vi.mock("@/lib/api/plainKnowledge", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/plainKnowledge")>()),
  useRoleProfiles: () => ({
    data: { items: [{ id: 5, slug: "tester", name: "Tester automatyzujący", summary: null, origin: "seed", status: "ready", jobs: 3, updated_at: null }] },
    isLoading: false,
    isError: false,
    error: null,
    isSuccess: true,
    refetch: vi.fn(),
  }),
  useRoleProfile: () => ({ data: ROLE, isLoading: false, isError: false, error: null, isSuccess: true, refetch: vi.fn() }),
  useUpdateRoleProfile: () => ({ mutate, isPending: false }),
}));

import { RoleLibraryTab } from "./RoleLibraryTab";

describe("RoleLibraryTab", () => {
  it("rola otwiera się jako opis do czytania; formularz dopiero po „Edytuj”", async () => {
    const user = userEvent.setup();
    render(<RoleLibraryTab />);

    const read = await screen.findByTestId("role-library-read");
    expect(within(read).getByText("Pisze testy, które same sprawdzają aplikację.")).toBeInTheDocument();
    expect(within(read).getByText("Pilnuje testów w CI")).toBeInTheDocument();
    expect(within(read).getByText("Selenium")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zapisz rolę" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: /Po ludzku/ })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Edytuj" }));
    expect(screen.getByRole("textbox", { name: /Po ludzku/ })).toHaveValue(
      "Pisze testy, które same sprawdzają aplikację.",
    );
    await user.click(screen.getByRole("button", { name: "Zamknij edycję" }));
    expect(screen.getByTestId("role-library-read")).toBeInTheDocument();
  });

  it("źródła i historia zmian w zakładkach, nie pod formularzem", async () => {
    const user = userEvent.setup();
    render(<RoleLibraryTab />);

    await screen.findByTestId("role-library-read");
    await user.click(screen.getByRole("tab", { name: "Źródła (0)" }));
    expect(screen.getByText("Opis bez źródeł z internetu.")).toBeInTheDocument();
    expect(screen.queryByTestId("role-library-read")).toBeNull();
  });
});
