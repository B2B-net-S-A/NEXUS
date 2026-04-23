import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  MultiSelectFilter,
  type MultiSelectFilterOption,
} from "@/components/v2/filters/MultiSelectFilter";

const STATUS_OPTIONS: ReadonlyArray<MultiSelectFilterOption<string>> = [
  { value: "active", label: "Aktywni" },
  { value: "passive", label: "Pasywni" },
  { value: "blacklisted", label: "Zablokowani" },
];

function setup(initial: string[] = []) {
  const onChange = vi.fn();
  const utils = render(
    <MultiSelectFilter
      value={initial}
      onChange={onChange}
      options={STATUS_OPTIONS}
      placeholder="Wszystkie statusy"
      searchPlaceholder="Szukaj statusu…"
    />,
  );
  return { ...utils, onChange };
}

describe("MultiSelectFilter", () => {
  it("renders placeholder when nothing selected", () => {
    setup();
    expect(screen.getByRole("button", { name: /Wszystkie statusy/i })).toBeInTheDocument();
  });

  it("shows the option label when exactly one value is selected", () => {
    setup(["active"]);
    expect(screen.getByRole("button", { name: /Aktywni/i })).toBeInTheDocument();
  });

  it("shows count when more than one value selected", () => {
    setup(["active", "passive"]);
    expect(screen.getByRole("button", { name: /2 wybrane/i })).toBeInTheDocument();
  });

  it("toggles a value on click — adds it to selection", async () => {
    const user = userEvent.setup();
    const { onChange } = setup();
    await user.click(screen.getByRole("button", { name: /Wszystkie statusy/i }));
    await user.click(await screen.findByText("Aktywni"));
    expect(onChange).toHaveBeenLastCalledWith(["active"]);
  });

  it("toggles off an already-selected value", async () => {
    const user = userEvent.setup();
    const { onChange } = setup(["active", "passive"]);
    await user.click(screen.getByRole("button"));
    await user.click(await screen.findByText("Aktywni"));
    expect(onChange).toHaveBeenLastCalledWith(["passive"]);
  });

  it("'Zaznacz wszystkie' selects every option", async () => {
    const user = userEvent.setup();
    const { onChange } = setup();
    await user.click(screen.getByRole("button"));
    await user.click(await screen.findByText("Zaznacz wszystkie"));
    expect(onChange).toHaveBeenLastCalledWith(["active", "passive", "blacklisted"]);
  });

  it("'Wyczyść' empties the selection", async () => {
    const user = userEvent.setup();
    const { onChange } = setup(["active", "passive"]);
    await user.click(screen.getByRole("button"));
    await user.click(await screen.findByText("Wyczyść"));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });
});
