/**
 * Komórka „Etapy” wiersza listy: osiem liczb i wyróżnienie „QC CV”, gdy na
 * wysyłkę patrzącego Delivery Leada czekają gotowe osoby (13.10.2026). Bez
 * nowej kolumny — tabela ledwo mieści się przy 1280 px.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { JobStageCounts, dlReadyLabel } from "@/components/v2/jobs/JobListCells";
import type { PipelineStageSummary } from "@/lib/job-pipeline-funnel";

const summary: PipelineStageSummary = {
  stage_columns: [
    { stage: "new", name: "Nowy", count: 3, category: "internal", order: 0 },
    { stage: "interview", name: "QC CV", count: 5, category: "internal", order: 1 },
  ],
};

function qcCell(): HTMLElement {
  return screen.getByTestId("job-stage-counts").querySelector('[data-group="cv_qc"]') as HTMLElement;
}

describe("dlReadyLabel — odmiana", () => {
  it("1 gotowa · 2–4 gotowe · 5+ gotowych (12–14 też „gotowych”)", () => {
    expect(dlReadyLabel(1)).toBe("1 gotowa do wysłania — czeka na Ciebie");
    expect(dlReadyLabel(2)).toBe("2 gotowe do wysłania — czeka na Ciebie");
    expect(dlReadyLabel(4)).toBe("4 gotowe do wysłania — czeka na Ciebie");
    expect(dlReadyLabel(5)).toBe("5 gotowych do wysłania — czeka na Ciebie");
    expect(dlReadyLabel(12)).toBe("12 gotowych do wysłania — czeka na Ciebie");
    expect(dlReadyLabel(22)).toBe("22 gotowe do wysłania — czeka na Ciebie");
  });
});

describe("JobStageCounts — gotowi do wysłania u Delivery Leada", () => {
  it("wypełnia komórkę „QC CV”, dopisuje pierwszą linię dymka i nazwę dostępną", () => {
    render(<JobStageCounts summary={summary} dlReady={2} />);
    const cell = qcCell();
    expect(cell).toHaveAttribute("data-dl-ready", "true");
    expect(cell).toHaveClass("bg-primary", "text-primary-foreground");
    expect(cell).not.toHaveClass("bg-muted/60");
    expect(cell).toHaveTextContent("5");
    expect(cell.getAttribute("title")).toBe(
      "2 gotowe do wysłania — czeka na Ciebie\nQC CV: QC CV 5",
    );
    expect(screen.getByTestId("job-stage-counts")).toHaveAccessibleName(
      "Etapy: Nowi 3, Screening 0, Zweryfikowany 0, " +
        "QC CV 5 (2 gotowe do wysłania — czeka na Ciebie), CV wysłane 0, " +
        "Rozmowa u klienta 0, Akceptacja i umowa 0, Zatrudniony 0",
    );
    // Wyróżniona jest tylko ta jedna komórka.
    expect(document.querySelectorAll("[data-dl-ready]")).toHaveLength(1);
  });

  const notWaiting: Array<[string, number | null | undefined]> = [
    ["bez pola (rekruter, kafelek bez tej liczby)", undefined],
    ["null", null],
    ["zero — Delivery Lead, na którego nikt nie czeka", 0],
  ];

  it.each(notWaiting)("%s: komórka i nazwa bez zmian", (_name, dlReady) => {
    render(<JobStageCounts summary={summary} dlReady={dlReady} />);
    const cell = qcCell();
    expect(cell).not.toHaveAttribute("data-dl-ready");
    expect(cell).toHaveClass("bg-muted/60");
    expect(cell).not.toHaveClass("bg-primary");
    expect(cell.getAttribute("title")).toBe("QC CV: QC CV 5");
    expect(screen.getByTestId("job-stage-counts")).toHaveAccessibleName(
      "Etapy: Nowi 3, Screening 0, Zweryfikowany 0, QC CV 5, CV wysłane 0, " +
        "Rozmowa u klienta 0, Akceptacja i umowa 0, Zatrudniony 0",
    );
  });
});
