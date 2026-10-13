import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppearanceMenu } from "@/components/v2/shell/AppearanceMenu";
import { useThemeStore } from "@/store/theme";

const celebrate = vi.hoisted(() => vi.fn());
vi.mock("@/lib/celebrate", () => ({ celebrate }));

beforeEach(() => {
  celebrate.mockReset();
  useThemeStore.setState({ theme: "light", kidsMode: false });
});

async function openMenu() {
  await userEvent.click(await screen.findByRole("button", { name: "Wygląd" }));
}

describe("AppearanceMenu", () => {
  it("jeden przycisk „Wygląd” z motywem, stylem, trybem gry i trybem ciemnym", async () => {
    render(<AppearanceMenu />);
    await openMenu();
    expect(await screen.findByText("Motyw koloru")).toBeInTheDocument();
    expect(screen.getByText("Styl interfejsu")).toBeInTheDocument();
    expect(screen.getByRole("menuitemcheckbox", { name: "Tryb gry" })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("menuitemcheckbox", { name: "Tryb ciemny" })).toHaveAttribute("aria-checked", "false");
  });

  it("tryb ciemny przełącza motyw w sklepie", async () => {
    render(<AppearanceMenu />);
    await openMenu();
    await userEvent.click(await screen.findByRole("menuitemcheckbox", { name: "Tryb ciemny" }));
    expect(useThemeStore.getState().theme).toBe("dark");
  });

  it("tryb gry wita tylko przy włączeniu", async () => {
    render(<AppearanceMenu />);
    await openMenu();
    await userEvent.click(await screen.findByRole("menuitemcheckbox", { name: "Tryb gry" }));
    expect(useThemeStore.getState().kidsMode).toBe(true);
    expect(celebrate).toHaveBeenCalledTimes(1);

    await openMenu();
    await userEvent.click(await screen.findByRole("menuitemcheckbox", { name: "Tryb gry" }));
    expect(useThemeStore.getState().kidsMode).toBe(false);
    expect(celebrate).toHaveBeenCalledTimes(1);
  });
});
