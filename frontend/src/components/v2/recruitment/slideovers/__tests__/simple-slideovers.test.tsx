import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const spies = vi.hoisted(() => ({ questionBank: vi.fn(), panel: vi.fn(), files: vi.fn() }));

vi.mock("@/components/prep/QuestionBankTab", () => ({
  QuestionBankTab: (props: unknown) => {
    spies.questionBank(props);
    return <div data-testid="question-bank" />;
  },
}));
vi.mock("@/components/v2/recruitment/ManualSearchPanel", () => ({
  ManualSearchPanel: (props: unknown) => {
    spies.panel(props);
    return <div data-testid="manual-search-panel" />;
  },
}));

vi.mock("@/components/v2/jobs/files/JobFilesPanel", () => ({
  JobFilesPanel: (props: unknown) => {
    spies.files(props);
    return <div data-testid="job-files-panel" />;
  },
}));

import { JobFilesSlideOver } from "../JobFilesSlideOver";
import { ManualSearchSlideOver } from "../ManualSearchSlideOver";
import { QuestionBankSlideOver } from "../QuestionBankSlideOver";
import { renderWithQuery } from "./test-utils";

describe("QuestionBankSlideOver", () => {
  it("zamknięte nie montuje banku pytań; otwarte przekazuje propsy strony", () => {
    const view = renderWithQuery(
      <QuestionBankSlideOver open={false} onOpenChange={vi.fn()} jobId={7} clientId={3} />,
    );
    expect(screen.queryByTestId("question-bank")).not.toBeInTheDocument();
    view.unmount();

    renderWithQuery(
      <QuestionBankSlideOver open onOpenChange={vi.fn()} jobId={7} clientId={3} readOnly />,
    );
    expect(screen.getByRole("dialog", { name: "Baza pytań" })).toBeInTheDocument();
    expect(spies.questionBank).toHaveBeenLastCalledWith({ jobId: 7, clientId: 3, readOnly: true });
  });
});

describe("JobFilesSlideOver", () => {
  it("zamknięte nie montuje listy; otwarte pokazuje pliki TEJ rekrutacji", () => {
    const view = renderWithQuery(<JobFilesSlideOver open={false} onOpenChange={vi.fn()} jobId={7} />);
    expect(screen.queryByTestId("job-files-panel")).not.toBeInTheDocument();
    view.unmount();

    renderWithQuery(<JobFilesSlideOver open onOpenChange={vi.fn()} jobId={7} />);
    expect(screen.getByRole("dialog", { name: "Pliki" })).toBeInTheDocument();
    expect(spies.files).toHaveBeenLastCalledWith(
      expect.objectContaining({ owner: { kind: "job", id: 7 }, editable: true }),
    );
  });

  it("tryb tylko do odczytu strony wyłącza dodawanie i usuwanie", () => {
    renderWithQuery(<JobFilesSlideOver open onOpenChange={vi.fn()} jobId={7} readOnly />);
    expect(spies.files).toHaveBeenLastCalledWith(expect.objectContaining({ editable: false }));
  });
});

describe("ManualSearchSlideOver", () => {
  const job = { id: 7, title: "Java Developer" };

  it("zamknięte nie montuje wyszukiwarki", () => {
    renderWithQuery(
      <ManualSearchSlideOver open={false} onOpenChange={vi.fn()} jobId={7} job={job} />,
    );
    expect(screen.queryByTestId("manual-search-panel")).not.toBeInTheDocument();
  });

  it("otwarte: szerokie okno z tytułem i panelem zasilonym rekrutacją", () => {
    const onBulkAdded = vi.fn();
    renderWithQuery(
      <ManualSearchSlideOver open onOpenChange={vi.fn()} jobId={7} job={job} onBulkAdded={onBulkAdded} />,
    );
    const dialog = screen.getByRole("dialog", { name: "Szukaj ręcznie" });
    expect(dialog.className).toContain("sm:max-w-[min(1100px,92vw)]");
    expect(spies.panel).toHaveBeenLastCalledWith({ jobId: 7, job, onBulkAdded, readOnly: false });
  });

  it("bez wczytanej rekrutacji mówi o ładowaniu zamiast montować panel", () => {
    renderWithQuery(<ManualSearchSlideOver open onOpenChange={vi.fn()} jobId={7} job={null} />);
    expect(screen.getByText("Ładowanie rekrutacji…")).toBeInTheDocument();
    expect(screen.queryByTestId("manual-search-panel")).not.toBeInTheDocument();
  });
});
