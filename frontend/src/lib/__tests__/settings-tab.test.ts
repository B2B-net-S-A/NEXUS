import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useSettingsTab, writeSettingsTabToUrl } from "@/lib/settings-tab";

// UAT M11-B01: zakładka Ustawień nie była w adresie — F5 i `?tab=` zawsze
// otwierały Integracje.
describe("useSettingsTab", () => {
  afterEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("startuje na zakładce z adresu", () => {
    const { result } = renderHook(() => useSettingsTab("administracja", vi.fn()));
    expect(result.current[0]).toBe("administracja");
  });

  it("nieznana albo pusta wartość = Integracje", () => {
    expect(renderHook(() => useSettingsTab("xyz", vi.fn())).result.current[0]).toBe(
      "integracje",
    );
    expect(renderHook(() => useSettingsTab(null, vi.fn())).result.current[0]).toBe(
      "integracje",
    );
  });

  it("miękka nawigacja do innego `?tab=` przełącza zakładkę", () => {
    const { result, rerender } = renderHook(
      ({ tab }: { tab: string | null }) => useSettingsTab(tab, vi.fn()),
      { initialProps: { tab: null as string | null } },
    );
    rerender({ tab: "historia" });
    expect(result.current[0]).toBe("historia");
  });

  it("miękka nawigacja na `/settings` bez `?tab=` wraca do zakładki domyślnej", () => {
    const { result, rerender } = renderHook(
      ({ tab }: { tab: string | null }) => useSettingsTab(tab, vi.fn()),
      { initialProps: { tab: "administracja" as string | null } },
    );
    expect(result.current[0]).toBe("administracja");
    rerender({ tab: null });
    expect(result.current[0]).toBe("integracje");
  });

  it("wybór zakładki trafia do adresu, a domyślna go czyści", () => {
    window.history.replaceState(null, "", "/settings");
    const { result } = renderHook(() => useSettingsTab(null));
    act(() => result.current[1]("szablony"));
    expect(result.current[0]).toBe("szablony");
    expect(window.location.search).toBe("?tab=szablony");

    writeSettingsTabToUrl("integracje");
    expect(window.location.search).toBe("");
  });
});
