import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { useUrlWriter } from "@/lib/url-selection";

describe("useUrlWriter — stan widoku w adresie bez przewijania strony", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/clients/7?tab=profil");
    router.replace.mockReset();
    router.push.mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    window.history.replaceState(null, "", "/");
  });

  it("ta sama ścieżka: zapis natywną historią ze stanem null, router nietknięty", () => {
    const replaceState = vi.spyOn(window.history, "replaceState");
    const { result } = renderHook(() => useUrlWriter());
    result.current.replaceUrl("/clients/7?tab=zamowienia");
    // Stan `null`: z `history.state` Next nie przeniósłby adresu do `useSearchParams`.
    expect(replaceState).toHaveBeenCalledWith(null, "", "/clients/7?tab=zamowienia");
    expect(window.location.search).toBe("?tab=zamowienia");
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("pushUrl dokłada wpis historii — „Wstecz” cofa ten krok", () => {
    const pushState = vi.spyOn(window.history, "pushState");
    const before = window.history.length;
    const { result } = renderHook(() => useUrlWriter());
    result.current.pushUrl("/clients/7?tab=importy-md");
    expect(pushState).toHaveBeenCalledWith(null, "", "/clients/7?tab=importy-md");
    expect(window.history.length).toBe(before + 1);
    expect(router.push).not.toHaveBeenCalled();
  });

  it("sam adres bez parametrów i z kotwicą też zostaje poza routerem", () => {
    const replaceState = vi.spyOn(window.history, "replaceState");
    const { result } = renderHook(() => useUrlWriter());
    result.current.replaceUrl("/clients/7");
    result.current.replaceUrl("/clients/7?tab=profil#umowy");
    // Względny adres z samymi parametrami zostaje na bieżącej stronie.
    result.current.replaceUrl("?tab=importy-md#umowy");
    expect(replaceState).toHaveBeenCalledTimes(3);
    expect(window.location.pathname).toBe("/clients/7");
    expect(window.location.search).toBe("?tab=importy-md");
    expect(window.location.hash).toBe("#umowy");
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("inna ścieżka to zwykła nawigacja — idzie przez router, adres zmienia dopiero on", () => {
    const replaceState = vi.spyOn(window.history, "replaceState");
    const pushState = vi.spyOn(window.history, "pushState");
    const { result } = renderHook(() => useUrlWriter());
    result.current.replaceUrl("/contracts/b2b-generator?tab=generator&edit=5");
    result.current.pushUrl("/insights?tab=firma");
    expect(router.replace).toHaveBeenCalledWith("/contracts/b2b-generator?tab=generator&edit=5", {
      scroll: false,
    });
    expect(router.push).toHaveBeenCalledWith("/insights?tab=firma", { scroll: false });
    expect(replaceState).not.toHaveBeenCalled();
    expect(pushState).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe("/clients/7");
  });

  it("pushUrl na adres, który już stoi, nie dokłada wpisu historii", () => {
    const pushState = vi.spyOn(window.history, "pushState");
    const before = window.history.length;
    const { result } = renderHook(() => useUrlWriter());
    result.current.pushUrl("/clients/7?tab=profil");
    expect(pushState).not.toHaveBeenCalled();
    expect(window.history.length).toBe(before);
    expect(router.push).not.toHaveBeenCalled();
  });

  describe("wpis historii prowadzony przez Next (`__NA`)", () => {
    beforeEach(() => {
      window.history.replaceState({ __NA: true }, "", "/clients/7?tab=profil");
    });

    it("Next przejął historię: stan routera zostaje, router nie jest wołany", () => {
      // Tak działa łatka Next: dokleja swój stan do wpisu i sam odświeża adres.
      const native = window.history.replaceState.bind(window.history);
      vi.spyOn(window.history, "replaceState").mockImplementation((data, unused, url) =>
        native({ ...(data as object | null), __NA: true }, unused, url),
      );
      const { result } = renderHook(() => useUrlWriter());
      result.current.replaceUrl("/clients/7?tab=zamowienia");
      expect(window.location.search).toBe("?tab=zamowienia");
      expect(router.replace).not.toHaveBeenCalled();
    });

    it("zapis sprzed przejęcia historii przez Next (efekt w pierwszej klatce) naprawia router", () => {
      const { result } = renderHook(() => useUrlWriter());
      // Bez łatki natywny zapis zostawia wpis bez stanu routera.
      result.current.replaceUrl("/clients/7?tab=zamowienia");
      expect(window.history.state).toBeNull();
      expect(router.replace).toHaveBeenCalledWith("/clients/7?tab=zamowienia", { scroll: false });
      router.replace.mockReset();
      window.history.replaceState({ __NA: true }, "", "/clients/7?tab=profil");
      result.current.pushUrl("/clients/7?tab=importy-md");
      expect(router.replace).toHaveBeenCalledWith("/clients/7?tab=importy-md", { scroll: false });
    });
  });

  it("funkcje są stabilne między renderami — nadają się do zależności efektów", () => {
    const { result, rerender } = renderHook(() => useUrlWriter());
    const first = result.current;
    rerender();
    expect(result.current.replaceUrl).toBe(first.replaceUrl);
    expect(result.current.pushUrl).toBe(first.pushUrl);
  });
});
