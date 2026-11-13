import { render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppearanceSync } from "@/components/v2/shell/AppearanceSync";
import { useThemeStore } from "@/store/theme";

// Hook czyta przez klienta `api` — mockujemy go, odpowiedzi jak z serwera.
const prefsApi = vi.hoisted(() => ({ get: vi.fn(), update: vi.fn() }));
vi.mock("@/lib/api", () => ({
  api: {
    get: async () => ({ data: await prefsApi.get() }),
    patch: async (_url: string, body: unknown) => ({ data: await prefsApi.update(body) }),
  },
}));

const BASE = {
  kpi_coach_enabled: true,
  daily_digest_email_enabled: false,
  daily_digest_email_available: false,
  stage_moves_all_led_jobs: false,
};

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AppearanceSync />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  prefsApi.get.mockReset();
  prefsApi.update.mockReset().mockImplementation(async (u: unknown) => ({ ...BASE, ...(u as object) }));
  useThemeStore.setState({ kidsMode: false, world: "none", worldBeforeSeason: null });
});

describe("świat na koncie", () => {
  it("przy wczytaniu wygrywa konto", async () => {
    useThemeStore.setState({ world: "latte" });
    prefsApi.get.mockResolvedValue({ ...BASE, appearance: { world: "winter", world_before_season: "sakura" } });
    mount();
    await waitFor(() => expect(useThemeStore.getState().world).toBe("winter"));
    expect(useThemeStore.getState().worldBeforeSeason).toBe("sakura");
    expect(prefsApi.update).not.toHaveBeenCalled();
  });

  it("konto bez zapisu dostaje wybór z przeglądarki, także tryb gry", async () => {
    useThemeStore.setState({ kidsMode: true });
    prefsApi.get.mockResolvedValue({ ...BASE, appearance: { world: null, world_before_season: null } });
    mount();
    await waitFor(() =>
      expect(prefsApi.update).toHaveBeenCalledWith({ appearance: { world: "game", world_before_season: null } })
    );
  });

  it("zmiana w galerii idzie na konto", async () => {
    prefsApi.get.mockResolvedValue({ ...BASE, appearance: { world: "none", world_before_season: null } });
    mount();
    await waitFor(() => expect(prefsApi.get).toHaveBeenCalled());
    await waitFor(() => expect(useThemeStore.getState().world).toBe("none"));
    useThemeStore.getState().setWorld("rgb");
    await waitFor(() =>
      expect(prefsApi.update).toHaveBeenCalledWith({ appearance: { world: "rgb", world_before_season: null } })
    );
  });

  it("serwer bez pola świata — nic nie zapisujemy", async () => {
    useThemeStore.setState({ world: "sakura" });
    prefsApi.get.mockResolvedValue({ ...BASE });
    mount();
    await waitFor(() => expect(prefsApi.get).toHaveBeenCalled());
    useThemeStore.getState().setWorld("latte");
    await new Promise((r) => setTimeout(r, 20));
    expect(prefsApi.update).not.toHaveBeenCalled();
    expect(useThemeStore.getState().world).toBe("latte");
  });
});
