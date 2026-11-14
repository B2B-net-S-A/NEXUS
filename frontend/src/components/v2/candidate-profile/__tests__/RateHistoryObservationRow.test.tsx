import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ObservationRow } from "../RateHistoryDialog";
import type { RateObservation } from "@/lib/api/candidateRates";

// Plakietka powodu w „Historii stawek” zawija się w wąskiej kolumnie
// („pracuje u nas — liczy się umowa”). Stała wysokość wariantu `md` (`h-5`)
// wypychała wtedy drugą linię poza ramkę (tester, staging 14.11.2026).
describe("ObservationRow — plakietka powodu", () => {
  it("rośnie razem z zawiniętym tekstem zamiast trzymać stałą wysokość", () => {
    const observation = {
      key: "contract:1",
      at: "2026-10-20T00:00:00Z",
      amount_hourly: 80,
      raw: "80 PLN/h · umowa",
      source: "contract",
      reason: "contract",
    } as unknown as RateObservation;

    render(
      <table>
        <tbody>
          <ObservationRow
            observation={observation}
            canEdit={false}
            pending={false}
            onDecide={vi.fn()}
          />
        </tbody>
      </table>,
    );

    const badge = screen.getByText("pracuje u nas — liczy się umowa");
    expect(badge.className).toContain("whitespace-normal");
    expect(badge.className).toContain("h-auto");
    expect(badge.className).not.toMatch(/(^|\s)h-5(\s|$)/);
  });
});
