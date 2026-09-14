import { afterEach, describe, expect, it } from "vitest";

import {
  candidateRowTestId,
  focusCandidateRow,
  isRowActivationKey,
} from "@/components/v2/pages/candidate-list-helpers";

/**
 * UAT B22: po zamknięciu szybkiego podglądu fokus wraca na wiersz ostatnio
 * oglądanego kandydata. Wiersz jest wirtualizowany, więc helper mówi, czy
 * fokus udało się przywrócić (inaczej Radix zostawia domyślne zachowanie).
 */
describe("focusCandidateRow", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  function row(id: number, tabIndex = 0): HTMLDivElement {
    const el = document.createElement("div");
    el.setAttribute("data-testid", candidateRowTestId(id));
    el.tabIndex = tabIndex;
    document.body.appendChild(el);
    return el;
  }

  it("przenosi fokus na wiersz i potwierdza to wynikiem", () => {
    row(7);
    const target = row(9);
    expect(focusCandidateRow(9)).toBe(true);
    expect(document.activeElement).toBe(target);
  });

  it("brak wiersza (poza oknem wirtualizacji) albo brak id = false, fokus nietknięty", () => {
    row(7);
    expect(focusCandidateRow(123)).toBe(false);
    expect(focusCandidateRow(null)).toBe(false);
    expect(document.activeElement).toBe(document.body);
  });
});

describe("isRowActivationKey", () => {
  it("Enter i Spacja otwierają podgląd, inne klawisze nie", () => {
    expect(isRowActivationKey("Enter")).toBe(true);
    expect(isRowActivationKey(" ")).toBe(true);
    expect(isRowActivationKey("Tab")).toBe(false);
    expect(isRowActivationKey("ArrowDown")).toBe(false);
  });
});
