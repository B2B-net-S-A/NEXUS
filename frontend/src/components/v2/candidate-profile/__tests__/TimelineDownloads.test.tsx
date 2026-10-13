/**
 * Oś czasu (przełącznik „Zmiany etapów i automaty”): kolejne pobrania plików
 * z jednego dnia zwijają się w jedną linię „Pobrano pliki · N” (E4, 13.10.2026).
 * Każdy podgląd PDF zapisuje „Pobrano plik”, więc kilka otwarć CV zajmowało
 * cały ekran osi.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TimelineTab, collapseDownloadRuns } from "../Timeline";

const download = (id: number, timestamp: string, action = "document_downloaded") => ({
  type: "activity",
  id,
  action,
  timestamp,
  details: { doc_id: id },
});

const stage = (id: number, timestamp: string) => ({
  type: "stage_change",
  id,
  stage: "screening",
  moved_by_name: "Marta Testowa",
  timestamp,
});

describe("collapseDownloadRuns", () => {
  it("łączy tylko pobrania pod rząd, pojedyncze zostawia", () => {
    const rows = collapseDownloadRuns([
      download(1, "2026-09-28T12:00:00Z"),
      download(2, "2026-09-28T11:00:00Z", "cv_downloaded"),
      stage(3, "2026-09-28T10:00:00Z"),
      download(4, "2026-09-28T09:00:00Z"),
    ]);
    expect(rows.map((row) => (row.kind === "downloads" ? row.items.length : row.kind))).toEqual([
      2,
      "item",
      "item",
    ]);
  });
});

describe("TimelineTab — pobrania plików", () => {
  it("trzy pobrania z jednego dnia to jedna linia, rozwijana na żądanie", () => {
    render(
      <TimelineTab
        items={[
          stage(10, "2026-09-28T13:00:00Z"),
          download(11, "2026-09-28T12:00:00Z"),
          download(12, "2026-09-28T11:30:00Z"),
          download(13, "2026-09-28T11:00:00Z"),
          // Inny dzień — osobna grupa, pojedyncze pobranie zostaje kartą.
          download(14, "2026-09-20T11:00:00Z"),
        ]}
      />,
    );
    const toggle = screen.getByRole("button", { name: /Pobrano pliki · 3/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // Jedna karta „Pobrano plik” z drugiego dnia, trzy schowane.
    expect(screen.getAllByText("Pobrano plik")).toHaveLength(1);

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByText("Pobrano plik")).toHaveLength(4);
  });

  it("jedno pobranie nie zwija się", () => {
    render(<TimelineTab items={[download(21, "2026-09-28T12:00:00Z")]} />);
    expect(screen.queryByRole("button", { name: /Pobrano pliki/ })).toBeNull();
    expect(screen.getByText("Pobrano plik")).toBeTruthy();
  });
});
