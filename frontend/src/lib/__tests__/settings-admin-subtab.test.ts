import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAdminSubTab, writeAdminSubTabToUrl } from "@/lib/settings-admin-subtab";
import { writeSettingsTabToUrl } from "@/lib/settings-tab";

// B42: podzakładka Administracji nie była w adresie — F5 na „Uprawnieniach"
// wracało do „Użytkowników".
describe("useAdminSubTab", () => {
  afterEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("startuje na podzakładce z adresu", () => {
    const { result } = renderHook(() => useAdminSubTab("permissions", vi.fn()));
    expect(result.current[0]).toBe("permissions");
  });

  it("nieznana albo pusta wartość = Użytkownicy", () => {
    expect(renderHook(() => useAdminSubTab("xyz", vi.fn())).result.current[0]).toBe(
      "users",
    );
    expect(renderHook(() => useAdminSubTab(null, vi.fn())).result.current[0]).toBe(
      "users",
    );
  });

  it("miękka nawigacja do innego `?sub=` przełącza podzakładkę", () => {
    const { result, rerender } = renderHook(
      ({ sub }: { sub: string | null }) => useAdminSubTab(sub, vi.fn()),
      { initialProps: { sub: null as string | null } },
    );
    rerender({ sub: "system" });
    expect(result.current[0]).toBe("system");
    rerender({ sub: null });
    expect(result.current[0]).toBe("users");
  });

  it("wybór podzakładki trafia do adresu obok `?tab=`, a domyślna go czyści", () => {
    window.history.replaceState(null, "", "/settings?tab=administracja");
    const { result } = renderHook(() => useAdminSubTab(null));
    act(() => result.current[1]("permissions"));
    expect(result.current[0]).toBe("permissions");
    expect(window.location.search).toBe("?tab=administracja&sub=permissions");

    writeAdminSubTabToUrl("users");
    expect(window.location.search).toBe("?tab=administracja");
  });

  it("zmiana głównej zakładki poza Administrację zdejmuje `?sub=`", () => {
    window.history.replaceState(null, "", "/settings?tab=administracja&sub=permissions");
    writeSettingsTabToUrl("procesy");
    expect(window.location.search).toBe("?tab=procesy");

    // Powrót na Administrację nie odtwarza podzakładki sam z siebie.
    writeSettingsTabToUrl("administracja");
    expect(window.location.search).toBe("?tab=administracja");
  });
});
