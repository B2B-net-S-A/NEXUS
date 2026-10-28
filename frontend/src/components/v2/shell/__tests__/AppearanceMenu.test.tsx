import { render as rtlRender, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppearanceMenu } from "@/components/v2/shell/AppearanceMenu";
import { useAuthStore } from "@/store/auth";
import { useThemeStore } from "@/store/theme";

const celebrate = vi.hoisted(() => vi.fn());
vi.mock("@/lib/celebrate", () => ({ celebrate }));

const jarvisApi = vi.hoisted(() => ({
  fetchJarvisPrefs: vi.fn(),
  saveJarvisPrefs: vi.fn(),
}));
vi.mock("@/lib/jarvis/api", () => ({
  jarvisKeys: { prefs: ["jarvis", "prefs"] },
  ...jarvisApi,
}));

function render(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return rtlRender(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  celebrate.mockReset();
  jarvisApi.fetchJarvisPrefs.mockReset().mockResolvedValue({ enabled: true });
  jarvisApi.saveJarvisPrefs.mockReset().mockImplementation(async (u: { enabled: boolean }) => u);
  useThemeStore.setState({ theme: "light", kidsMode: false });
  useAuthStore.setState({ token: "t", realUser: null });
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

  it("„Robot Jarvisa w rogu” chowa i przywraca robota na koncie", async () => {
    render(<AppearanceMenu />);
    await openMenu();
    const item = await screen.findByRole("menuitemcheckbox", { name: "Robot Jarvisa w rogu" });
    expect(item).toHaveAttribute("aria-checked", "true");
    await userEvent.click(item);
    await waitFor(() => expect(jarvisApi.saveJarvisPrefs).toHaveBeenCalledWith({ enabled: false }));

    await openMenu();
    const off = await screen.findByRole("menuitemcheckbox", { name: "Robot Jarvisa w rogu" });
    expect(off).toHaveAttribute("aria-checked", "false");
    await userEvent.click(off);
    await waitFor(() => expect(jarvisApi.saveJarvisPrefs).toHaveBeenLastCalledWith({ enabled: true }));
  });

  it("w trybie „podgląd jako” nie ma pozycji robota (Jarvis wtedy znika)", async () => {
    useAuthStore.setState({ token: "t", realUser: { id: 1 } as never });
    render(<AppearanceMenu />);
    await openMenu();
    await screen.findByRole("menuitemcheckbox", { name: "Tryb ciemny" });
    expect(screen.queryByRole("menuitemcheckbox", { name: "Robot Jarvisa w rogu" })).toBeNull();
    expect(jarvisApi.fetchJarvisPrefs).not.toHaveBeenCalled();
  });
});
