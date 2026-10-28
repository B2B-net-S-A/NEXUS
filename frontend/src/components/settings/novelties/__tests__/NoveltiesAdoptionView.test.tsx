import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NoveltiesAdoptionView } from "@/components/settings/novelties/NoveltiesAdoptionView";
import type { NoveltyAdoption } from "@/lib/novelties/api";

const item = (overrides: Partial<NoveltyAdoption> = {}): NoveltyAdoption => ({
  id: "wybieram",
  title: "„Wybieram” na profilu",
  tier: "tour",
  shipped_on: "2026-10-28",
  pr: 2757,
  where: "Rekrutacja",
  active: true,
  audience: 3,
  counts: { used: 1, tour: 0, dot: 0, seen: 1, untouched: 1 },
  people: [
    {
      user_id: 1,
      name: "Osoba Seen",
      state: "seen",
      completed_at: null,
      seen_count: 2,
      reminded_at: null,
    },
    {
      user_id: 2,
      name: "Osoba Nowa",
      state: "untouched",
      completed_at: null,
      seen_count: 0,
      reminded_at: null,
    },
    {
      user_id: 3,
      name: "Osoba Umie",
      state: "used",
      completed_at: "2026-10-28T12:00:00Z",
      seen_count: 1,
      reminded_at: null,
    },
  ],
  ...overrides,
});

describe("NoveltiesAdoptionView", () => {
  it("przypomina tylko tym, którzy jeszcze nie umieją", () => {
    const onRemind = vi.fn();
    render(
      <NoveltiesAdoptionView
        load={{ status: "success", items: [item()] }}
        onRetry={vi.fn()}
        onRemind={onRemind}
        remindingId={null}
      />,
    );
    expect(
      screen.getByText("2 z 3 osób jeszcze nie umie."),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: /Przypomnij 2 osobom/ }),
    );
    expect(onRemind).toHaveBeenCalledWith("wybieram", [1, 2]);
  });

  it("nowość, której już nie pokazujemy, nie ma przycisku przypomnienia", () => {
    render(
      <NoveltiesAdoptionView
        load={{ status: "success", items: [item({ active: false })] }}
        onRetry={vi.fn()}
        onRemind={vi.fn()}
        remindingId={null}
      />,
    );
    expect(screen.queryByRole("button", { name: /Przypomnij/ })).toBeNull();
  });

  it("awaria nie wygląda jak pusta lista", () => {
    render(
      <NoveltiesAdoptionView
        load={{
          status: "error",
          forbidden: false,
          message: "Serwer nie odpowiada.",
        }}
        onRetry={vi.fn()}
        onRemind={vi.fn()}
        remindingId={null}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Serwer nie odpowiada.",
    );
    expect(screen.queryByText(/Brak nowości/)).toBeNull();
  });

  it("pusty stan tylko po udanym odczycie", () => {
    render(
      <NoveltiesAdoptionView
        load={{ status: "success", items: [] }}
        onRetry={vi.fn()}
        onRemind={vi.fn()}
        remindingId={null}
      />,
    );
    expect(
      screen.getByText("Brak nowości z ostatnich 90 dni"),
    ).toBeInTheDocument();
  });
});
