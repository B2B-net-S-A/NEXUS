/**
 * Szczegóły rekrutacji w Podglądzie listy: to, co zeszło z wiersza
 * (wymagania, nazwa od klienta, numery, tryb pracy, data otwarcia, podobne).
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  JobPreviewDetails,
  type JobPreviewDetailsJob,
} from "@/components/v2/jobs/JobPreviewDetails";

const showSuccess = vi.fn();
const showError = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError }),
}));

const copyMock = vi.fn();
vi.mock("@/lib/clipboard", () => ({
  copyTextToClipboard: (text: string) => copyMock(text),
}));

vi.mock("@/components/v2/CompetenceCategoryBadge", () => ({
  competenceShortLabel: () => null,
  competenceTone: () => "neutral",
  useCompetenceCategories: () => ({ data: [] }),
}));

const job: JobPreviewDetailsJob = {
  id: 7,
  title: "Programista Python",
  working_title: "Programista Python · Python, Microservices · 6+ lat",
  must_skills: ["Python", { name: "Microservices" }],
  client_reference: "ZOB-2947",
  reference_number: "PB/004/2026",
  remote_policy: "hybrid",
  onsite_days_per_month: 2,
  location: "Warszawa",
  opened_effective_at: "2026-09-30T08:00:00Z",
  similar: {
    linked_count: 0,
    linked_first: null,
    reassigned_count: 0,
    suggested: {
      count: 5,
      sent_count: 24,
      first: { id: 9, title: "Python", reference_number: null },
    },
  },
};

beforeEach(() => {
  showSuccess.mockReset();
  showError.mockReset();
  copyMock.mockReset();
});

describe("JobPreviewDetails", () => {
  it("pokazuje wymagania, nazwy i numery, tryb pracy, datę otwarcia i podobne rekrutacje", async () => {
    const onSimilar = vi.fn();
    render(<JobPreviewDetails job={job} onSimilar={onSimilar} />);

    const requirements = within(screen.getByRole("list"));
    expect(requirements.getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Python",
      "Microservices",
    ]);
    expect(screen.getByText("Nazwa od klienta").nextElementSibling).toHaveTextContent(
      "Programista Python",
    );
    expect(screen.getByText("Numer u klienta").nextElementSibling).toHaveTextContent("ZOB-2947");
    expect(screen.getByText("Nasz numer").nextElementSibling).toHaveTextContent("PB/004/2026");
    expect(screen.getByText("Tryb pracy").nextElementSibling).toHaveTextContent(
      "Hybrydowo · 2 dni w miesiącu · Warszawa",
    );
    expect(screen.getByText("Otwarta").nextElementSibling).toHaveTextContent("30.09.2026");

    await userEvent.setup().click(screen.getByTestId("job-similar-badge"));
    expect(onSimilar).toHaveBeenCalledOnce();
  });

  it("wymagań jest najwyżej osiem, reszta jako „+N”", () => {
    const many = Array.from({ length: 11 }, (_, i) => `Skill ${i + 1}`);
    render(<JobPreviewDetails job={{ id: 1, must_skills: many }} onSimilar={vi.fn()} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(8);
    expect(screen.getByText("+3 — pełna lista w rekrutacji")).toBeInTheDocument();
  });

  it("wymaganie-zdanie stoi jako punkt listy, a słowo kluczowe jako chip", () => {
    const sentence =
      "Minimum 5 lat doświadczenia w analizie biznesowo-systemowej w dużych projektach";
    render(
      <JobPreviewDetails
        job={{ id: 1, must_skills: ["BPMN 2.0", sentence, "JIRA"] }}
        onSimilar={vi.fn()}
      />,
    );
    const chips = within(screen.getByTestId("job-preview-requirement-chips"));
    expect(chips.getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "BPMN 2.0",
      "JIRA",
    ]);
    const lines = within(screen.getByTestId("job-preview-requirement-lines"));
    expect(lines.getAllByRole("listitem").map((li) => li.textContent)).toEqual([sentence]);
  });

  it("kopiuje numer u klienta i mówi, gdy się nie udało", async () => {
    const user = userEvent.setup();
    render(<JobPreviewDetails job={job} onSimilar={vi.fn()} />);
    const copy = screen.getByRole("button", { name: "Kopiuj numer u klienta" });

    copyMock.mockResolvedValueOnce(true);
    await user.click(copy);
    expect(copyMock).toHaveBeenCalledWith("ZOB-2947");
    expect(showSuccess).toHaveBeenCalledWith("Skopiowano numer u klienta");

    copyMock.mockResolvedValueOnce(false);
    await user.click(copy);
    expect(showError).toHaveBeenCalledOnce();
  });

  it("puste pola się nie rysują; bez żadnych danych sekcji nie ma", () => {
    const { container, rerender } = render(
      <JobPreviewDetails job={{ id: 1, title: "Tester" }} onSimilar={vi.fn()} />,
    );
    expect(screen.getByText("Nazwa od klienta")).toBeInTheDocument();
    for (const label of ["Wymagania", "Numer u klienta", "Nasz numer", "Tryb pracy", "Otwarta", "Podobne rekrutacje"]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
    rerender(<JobPreviewDetails job={{ id: 1 }} onSimilar={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
