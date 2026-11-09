import * as React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AddedByCompactFilter, AddedByFilterButton } from "@/components/v2/jobs/AddedByFilter";
import { ADDED_BY_ALL, addedByOptions, type AddedByFilter } from "@/lib/board-added-by";

const person = (candidate_id: number, by: number | null, name: string | null = null) => ({
  candidate_id,
  added_to_job_by_id: by,
  added_to_job_by_name: name,
});

const OPTIONS = addedByOptions(
  [
    person(1, 7, "Tomasz Rybak"),
    person(2, 7, "Tomasz Rybak"),
    person(3, 8, "Paulina Wrona"),
    person(4, null),
  ],
  { id: 7, name: "Tomasz Rybak" },
);

function renderButton(value: AddedByFilter = ADDED_BY_ALL) {
  const onChange = vi.fn<(filter: AddedByFilter) => void>();
  render(<AddedByFilterButton options={OPTIONS} value={value} onChange={onChange} />);
  return { onChange };
}

describe("AddedByFilterButton — „Kto dodał” w nagłówku rekrutacji (D2)", () => {
  it("bez filtra: „Kto dodał: wszyscy”, bez „✕”", () => {
    renderButton();
    expect(screen.getByTestId("added-by-trigger")).toHaveTextContent("Kto dodał:wszyscy");
    expect(screen.queryByTestId("added-by-clear")).toBeNull();
  });

  it("menu: Wszyscy, Ty, inne osoby, Brak danych — z liczbami osób w toku", async () => {
    const { onChange } = renderButton();
    await userEvent.click(screen.getByTestId("added-by-trigger"));
    const menu = await screen.findByRole("menu");
    const labels = within(menu)
      .getAllByRole("menuitemradio")
      .map((el) => el.textContent);
    expect(labels).toEqual(["Wszyscy4", "Ty (Tomasz Rybak)2", "Paulina Wrona1", "Brak danych1"]);
    await userEvent.click(within(menu).getByTestId("added-by-option-user:7"));
    expect(onChange).toHaveBeenCalledWith({ kind: "user", userId: 7 });
  });

  it("z filtrem: mówi kogo i ile widać, „✕” wraca do wszystkich", async () => {
    const { onChange } = renderButton({ kind: "user", userId: 7 });
    const trigger = screen.getByTestId("added-by-trigger");
    expect(trigger).toHaveTextContent("Kto dodał:Ty· 2 z 4");
    expect(trigger).toHaveAccessibleName("Kto dodał: Ty. Widać 2 z 4 osób.");
    await userEvent.click(screen.getByTestId("added-by-clear"));
    expect(onChange).toHaveBeenCalledWith(ADDED_BY_ALL);
  });

  it("„Ty” bez żadnej osoby jest w menu, ale nie da się go wybrać", async () => {
    render(
      <AddedByFilterButton
        options={addedByOptions([person(3, 8, "Paulina Wrona")], { id: 7, name: null })}
        value={ADDED_BY_ALL}
        onChange={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByTestId("added-by-trigger"));
    const viewer = await screen.findByTestId("added-by-option-user:7");
    expect(viewer).toHaveAttribute("data-disabled");
  });
});

describe("AddedByCompactFilter — ikona w zwiniętym nagłówku (09.11.2026)", () => {
  function renderIcon(value: AddedByFilter = ADDED_BY_ALL) {
    const onChange = vi.fn<(filter: AddedByFilter) => void>();
    render(<AddedByCompactFilter options={OPTIONS} value={value} onChange={onChange} />);
    return { onChange };
  }

  it("podpis mówi, co jest wybrane, a menu zmienia filtr", async () => {
    const { onChange } = renderIcon();
    const icon = screen.getByRole("button", { name: "Kto dodał: wszyscy" });
    await userEvent.click(icon);
    await userEvent.click(within(screen.getByTestId("added-by-menu")).getByText(/Ty/));
    expect(onChange).toHaveBeenCalledWith({ kind: "user", userId: 7 });
  });

  it("włączony filtr widać na samej ikonie", () => {
    renderIcon({ kind: "user", userId: 7 });
    expect(screen.getByRole("button", { name: "Kto dodał: Ty" })).toHaveClass("bg-primary/10");
  });
});

describe("AddedByFilterButton — na stałe w pasku rekrutacji (09.11.2026)", () => {
  it("niesie kotwicę nowości i ma wysokość kafli źródeł", () => {
    renderButton();
    const trigger = screen.getByTestId("added-by-trigger");
    expect(trigger).toHaveAttribute("data-tour", "jobs.board.added-by");
    expect(trigger).toHaveClass("h-7");
  });
});
