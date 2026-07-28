import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useLocalStorageFlag } from "@/lib/use-local-storage-flag";

const KEY = "test_flag";

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("useLocalStorageFlag", () => {
  it("startuje na wartości domyślnej, gdy w storage nic nie ma", () => {
    const { result } = renderHook(() => useLocalStorageFlag(KEY));
    expect(result.current[0]).toBe(false);

    const { result: withDefault } = renderHook(() => useLocalStorageFlag(KEY, true));
    expect(withDefault.current[0]).toBe(true);
  });

  it("dociąga zapamiętaną wartość po zamontowaniu", () => {
    window.localStorage.setItem(KEY, "1");
    const { result } = renderHook(() => useLocalStorageFlag(KEY));
    expect(result.current[0]).toBe(true);
  });

  it('"0" w storage wygrywa z domyślnym true', () => {
    window.localStorage.setItem(KEY, "0");
    const { result } = renderHook(() => useLocalStorageFlag(KEY, true));
    expect(result.current[0]).toBe(false);
  });

  it("zapisuje do storage przy zmianie — także w wariancie funkcyjnym", () => {
    const { result } = renderHook(() => useLocalStorageFlag(KEY));

    act(() => result.current[1](true));
    expect(result.current[0]).toBe(true);
    expect(window.localStorage.getItem(KEY)).toBe("1");

    act(() => result.current[1]((previous) => !previous));
    expect(result.current[0]).toBe(false);
    expect(window.localStorage.getItem(KEY)).toBe("0");
  });

  it("NIE nadpisuje zapamiętanej wartości przy samym montażu", () => {
    window.localStorage.setItem(KEY, "1");
    renderHook(() => useLocalStorageFlag(KEY, false));
    expect(window.localStorage.getItem(KEY)).toBe("1");
  });

  it("przeżywa storage rzucający wyjątkiem przy odczycie", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });

    const { result } = renderHook(() => useLocalStorageFlag(KEY, true));
    expect(result.current[0]).toBe(true);
  });

  it("przeżywa storage rzucający wyjątkiem przy zapisie — stan zostaje w pamięci", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });

    const { result } = renderHook(() => useLocalStorageFlag(KEY));
    expect(() => act(() => result.current[1](true))).not.toThrow();
    expect(result.current[0]).toBe(true);
  });
});
