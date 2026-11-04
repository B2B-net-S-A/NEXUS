import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

// Okno ma własne testy (`RequirementProposalDialog.test.tsx`) — tu tylko to,
// czy sekcja je otwiera i dla której rekrutacji.
vi.mock("@/components/champion/RequirementProposalDialog", () => ({
  championEditHref: (jobId: number) => `/jobs/${jobId}?tab=champion&mode=edit`,
  RequirementProposalDialog: ({ jobId, jobTitle }: { jobId: number; jobTitle?: string }) => (
    <div role="dialog" aria-label="Uporządkowanie wymagań">
      rekrutacja {jobId} · {jobTitle}
    </div>
  ),
}));

import {
  REQUIREMENT_FIXES_ROWS,
  RequirementFixesSection,
  requirementFixCounts,
} from "@/components/v2/dashboard/RequirementFixesSection";
import type { RequirementFixRow } from "@/lib/api/boardTasks";

function fixRow(over: Partial<RequirementFixRow> = {}): RequirementFixRow {
  return {
    job_id: 41,
    title: "Programista Java",
    reasons: [
      { code: "prose_rows", text: "zdania w wymaganiach — wyszukiwanie ich nie znajdzie" },
      { code: "paren", text: "komentarz w nawiasie wyłącza technologię z wyszukiwania" },
    ],
    can_apply: true,
    rows: 4,
    talk: 2,
    ...over,
  };
}

describe("RequirementFixesSection", () => {
  it("pokazuje rekrutację z powodami, liczbami i linkiem", () => {
    render(<RequirementFixesSection rows={[fixRow()]} />);
    const section = screen.getByRole("region", { name: "Wymagania do poprawy" });
    expect(within(section).getByRole("heading")).toHaveTextContent("Wymagania do poprawy (1)");
    expect(section).toHaveTextContent(
      "System rozdzielił wymagania: słowa do szukania i rzeczy do sprawdzenia w rozmowie. Zatwierdź albo odrzuć.",
    );
    expect(screen.getByRole("link", { name: "Programista Java" })).toHaveAttribute("href", "/jobs/41");
    expect(screen.getByTestId("requirement-fix-reasons")).toHaveTextContent(
      "zdania w wymaganiach — wyszukiwanie ich nie znajdzie · komentarz w nawiasie wyłącza technologię z wyszukiwania",
    );
    expect(screen.getByTestId("requirement-fix-counts")).toHaveTextContent(
      "4 słowa do szukania · 2 do rozmowy",
    );
  });

  it("„Pokaż zmiany” otwiera okno tej rekrutacji", async () => {
    const user = userEvent.setup();
    render(<RequirementFixesSection rows={[fixRow(), fixRow({ job_id: 42, title: "Tester" })]} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pokaż zmiany: Tester" }));
    expect(screen.getByRole("dialog", { name: "Uporządkowanie wymagań" })).toHaveTextContent(
      "rekrutacja 42 · Tester",
    );
  });

  it("bez słów do szukania prowadzi do Profilu Championa zamiast okna", () => {
    render(
      <RequirementFixesSection
        rows={[
          fixRow({
            can_apply: false,
            rows: 0,
            reasons: [{ code: "no_search_words", text: "brak słów do szukania" }],
          }),
        ]}
      />,
    );
    expect(screen.queryByRole("button", { name: /Pokaż zmiany/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Uzupełnij: Programista Java" })).toHaveAttribute(
      "href",
      "/jobs/41?tab=champion&mode=edit",
    );
    expect(screen.getByTestId("requirement-fix-counts")).toHaveTextContent("0 słów do szukania");
  });

  it("pusta lista nic nie rysuje", () => {
    const { container, rerender } = render(<RequirementFixesSection rows={[]} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<RequirementFixesSection rows={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("zwinięta (Head, admin) to jedna linia z „Rozwiń”", async () => {
    const user = userEvent.setup();
    render(<RequirementFixesSection rows={[fixRow(), fixRow({ job_id: 42 })]} collapsed />);
    expect(screen.getByTestId("requirement-fixes-collapsed")).toHaveTextContent(
      "Wymagania do poprawy (2)",
    );
    expect(screen.queryByRole("button", { name: /Pokaż zmiany/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Rozwiń" }));
    expect(screen.getAllByRole("button", { name: /Pokaż zmiany/ })).toHaveLength(2);
  });

  it("długa lista chowa resztę pod „Pokaż wszystkie”", async () => {
    const user = userEvent.setup();
    const rows = Array.from({ length: REQUIREMENT_FIXES_ROWS + 2 }, (_, i) =>
      fixRow({ job_id: 100 + i, title: `Rekrutacja ${i}` }),
    );
    render(<RequirementFixesSection rows={rows} />);
    expect(screen.getAllByRole("button", { name: /Pokaż zmiany/ })).toHaveLength(REQUIREMENT_FIXES_ROWS);
    await user.click(screen.getByRole("button", { name: `Pokaż wszystkie (${rows.length})` }));
    expect(screen.getAllByRole("button", { name: /Pokaż zmiany/ })).toHaveLength(rows.length);
  });

  it("liczby w polskiej odmianie", () => {
    expect(requirementFixCounts({ rows: 1, talk: 0 })).toBe("1 słowo do szukania · 0 do rozmowy");
    expect(requirementFixCounts({ rows: 5, talk: 3 })).toBe("5 słów do szukania · 3 do rozmowy");
  });
});
