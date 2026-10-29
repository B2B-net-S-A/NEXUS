import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  DepartedCareSection,
  departedCareCount,
} from "@/components/v2/dashboard/DepartedCareSection";
import type { DepartedCareResponse } from "@/lib/departed-care";

const DATA: DepartedCareResponse = {
  total: 78,
  escalate_after_days: 10,
  overdue: [],
  groups: [
    {
      departed_user_id: 227,
      departed_name: "Anna Przykładowa",
      since: "2026-10-13T08:00:00Z",
      pairs: 78,
      jobs: 7,
      clients: ["Bank Przykładowy"],
      columns: { client_interview: 3, cv_sent: 18, new: 57 },
      rows: [],
    },
  ],
};

describe("DepartedCareSection", () => {
  it("mówi, po kim i ile zostało, i prowadzi do listy", () => {
    render(<DepartedCareSection data={DATA} failed={false} expanded={false} onToggle={vi.fn()} />);
    expect(screen.getByRole("region", { name: "Po osobach, które odeszły" })).toBeInTheDocument();
    expect(screen.getByText("Anna P.")).toBeInTheDocument();
    expect(screen.getByText("78 osób")).toBeInTheDocument();
    expect(screen.getByText("3 rozmowa u klienta")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Otwórz listę" })).toHaveAttribute(
      "href",
      "/departed-care?from=227",
    );
  });

  it("Head of Recruitment widzi DL-i po terminie", () => {
    render(
      <DepartedCareSection
        data={{
          ...DATA,
          groups: [],
          total: 0,
          overdue: [
            { user_id: 86, name: "Maria Opiekunka", pairs: 12, departed: ["Anna Przykładowa"], since: "2026-10-13T08:00:00Z" },
          ],
        }}
        failed={false}
        expanded={false}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByText(/12 osób niedomkniętych/)).toBeInTheDocument();
    expect(screen.getByText(/po: Anna P\./)).toBeInTheDocument();
  });

  it("awaria nie wygląda jak „nic nie czeka”", () => {
    render(<DepartedCareSection data={undefined} failed expanded={false} onToggle={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Nie udało się sprawdzić");
  });

  it("nic do domknięcia — bez kafla i bez licznika", () => {
    const { container } = render(
      <DepartedCareSection
        data={{ ...DATA, groups: [], total: 0 }}
        failed={false}
        expanded={false}
        onToggle={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(departedCareCount(undefined)).toBe(0);
    expect(departedCareCount(DATA)).toBe(1);
  });
});
