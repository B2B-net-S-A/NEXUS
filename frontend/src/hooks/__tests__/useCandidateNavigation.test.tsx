import * as React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import api from "@/lib/api";
import { DEFAULT_FILTERS } from "@/lib/url-filters";
import { useCandidateNavigation } from "@/hooks/useCandidateNavigation";

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn() },
}));

const apiGet = vi.mocked(api.get);

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useCandidateNavigation", () => {
  beforeEach(() => {
    apiGet.mockReset();
  });

  it("uses J/K and ignores shortcuts while typing", () => {
    const onNavigate = vi.fn();
    const { rerender } = renderHook(
      ({ position }) =>
        useCandidateNavigation({
          mode: "embedded",
          enabled: true,
          filters: DEFAULT_FILTERS,
          position,
          pageItems: [{ id: 10 }, { id: 11 }],
          total: 2,
          pageNumber: 1,
          pageSize: 20,
          onNavigate,
        }),
      { wrapper, initialProps: { position: 1 } },
    );

    act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "j" })));
    expect(onNavigate).toHaveBeenCalledWith({ candidateId: 11, position: 2 });

    rerender({ position: 2 });
    act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "K" })));
    expect(onNavigate).toHaveBeenLastCalledWith({ candidateId: 10, position: 1 });

    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "j" })));
    expect(onNavigate).toHaveBeenCalledTimes(2);
    input.remove();
  });

  it("fetches adjacent pages without expensive include flags and exposes errors", async () => {
    apiGet.mockRejectedValueOnce(new Error("offline"));
    const { result } = renderHook(
      () =>
        useCandidateNavigation({
          mode: "embedded",
          enabled: true,
          filters: DEFAULT_FILTERS,
          position: 1,
          pageItems: [{ id: 10 }],
          total: 2,
          pageNumber: 1,
          pageSize: 1,
          onNavigate: vi.fn(),
        }),
      { wrapper },
    );

    act(() => result.current.goNext());
    await waitFor(() =>
      expect(result.current.error).toBe(
        "Nie udało się pobrać kolejnego kandydata",
      ),
    );

    expect(apiGet).toHaveBeenCalledTimes(1);
    const config = apiGet.mock.calls[0]?.[1] as { params?: Record<string, unknown> };
    expect(config.params).not.toHaveProperty("include_match_stats");
    expect(config.params).not.toHaveProperty("include_active_recruitments");
    expect(config.params).not.toHaveProperty("include_last_activity");
  });
});

function stableWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function StableWrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return StableWrapper;
}

function page(items: Array<{ id: number }>, total: number, pageNumber = 1, pageSize = 20) {
  return { data: { items, total, page: pageNumber, page_size: pageSize } };
}

const press = (init: KeyboardEventInit) =>
  act(() => {
    document.dispatchEvent(new KeyboardEvent("keydown", init));
  });

function embedded(
  overrides: Partial<Parameters<typeof useCandidateNavigation>[0]> & { position: number },
  onNavigate = vi.fn(),
) {
  return {
    mode: "embedded" as const,
    enabled: true,
    filters: DEFAULT_FILTERS,
    pageItems: [{ id: 10 }, { id: 11 }, { id: 12 }],
    total: 3,
    pageNumber: 1,
    pageSize: 20,
    onNavigate,
    ...overrides,
  } as Parameters<typeof useCandidateNavigation>[0];
}

describe("useCandidateNavigation — tryb `url`", () => {
  beforeEach(() => {
    apiGet.mockReset();
  });

  it("pobiera stronę z pozycją (pos 25 → strona 2 po 20) i bierze z niej łączną liczbę", async () => {
    const items = Array.from({ length: 20 }, (_, i) => ({ id: 100 + i }));
    apiGet.mockResolvedValue(page(items, 41, 2));
    const onNavigate = vi.fn();
    const { result } = renderHook(
      () =>
        useCandidateNavigation({
          mode: "url",
          enabled: true,
          filters: DEFAULT_FILTERS,
          position: 25,
          onNavigate,
        }),
      { wrapper: stableWrapper() },
    );

    await waitFor(() => expect(result.current.total).toBe(41));
    expect(result.current).toMatchObject({ hasPrev: true, hasNext: true, error: null });
    const [url, config] = apiGet.mock.calls[0] as [
      string,
      { params: Record<string, unknown>; signal?: AbortSignal },
    ];
    expect(url).toBe("/api/candidates");
    expect(config.params).toMatchObject({ page: 2, page_size: 20 });
    expect(config.signal).toBeInstanceOf(AbortSignal);

    // Sąsiad na tej samej stronie — bez nowego zapytania.
    act(() => result.current.goNext());
    expect(onNavigate).toHaveBeenCalledWith({ candidateId: 105, position: 26 });
    act(() => result.current.goPrev());
    expect(onNavigate).toHaveBeenLastCalledWith({ candidateId: 103, position: 24 });
    expect(apiGet).toHaveBeenCalledTimes(1);
  });

  it("ostatnia pozycja listy: brak „następnego”, goNext nic nie robi", async () => {
    apiGet.mockResolvedValue(page([{ id: 1 }, { id: 2 }], 2));
    const onNavigate = vi.fn();
    const { result } = renderHook(
      () =>
        useCandidateNavigation({
          mode: "url",
          enabled: true,
          filters: DEFAULT_FILTERS,
          position: 2,
          onNavigate,
        }),
      { wrapper: stableWrapper() },
    );

    await waitFor(() => expect(result.current.total).toBe(2));
    expect(result.current.hasNext).toBe(false);
    act(() => result.current.goNext());
    press({ key: "j" });
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("awaria listy to komunikat, a „Spróbuj ponownie” czyści go i pyta jeszcze raz", async () => {
    apiGet.mockRejectedValueOnce(new Error("503"));
    const { result } = renderHook(
      () =>
        useCandidateNavigation({
          mode: "url",
          enabled: true,
          filters: DEFAULT_FILTERS,
          position: 1,
          onNavigate: vi.fn(),
        }),
      { wrapper: stableWrapper() },
    );

    await waitFor(() =>
      expect(result.current.error).toBe("Nie udało się pobrać listy kandydatów"),
    );
    // Awaria nie może wyglądać jak „0 z 0” z aktywną nawigacją.
    expect(result.current).toMatchObject({ total: 0, hasNext: false, hasPrev: false });

    apiGet.mockResolvedValueOnce(page([{ id: 1 }, { id: 2 }], 2));
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.error).toBeNull());
    expect(result.current.total).toBe(2);
    expect(apiGet).toHaveBeenCalledTimes(2);
  });

  it("`enabled: false` nie pyta serwera i wyłącza nawigację", async () => {
    const onNavigate = vi.fn();
    const { result } = renderHook(
      () =>
        useCandidateNavigation({
          mode: "url",
          enabled: false,
          filters: DEFAULT_FILTERS,
          position: 3,
          onNavigate,
        }),
      { wrapper: stableWrapper() },
    );

    expect(result.current).toMatchObject({ hasPrev: false, hasNext: false, total: 0 });
    act(() => result.current.goPrev());
    press({ key: "k" });
    expect(onNavigate).not.toHaveBeenCalled();
    expect(apiGet).not.toHaveBeenCalled();
  });
});

describe("useCandidateNavigation — tryb `embedded`, granice stron i klawisze", () => {
  beforeEach(() => {
    apiGet.mockReset();
  });

  it("strona rodzica w pamięci — bez zapytania przy wejściu", () => {
    const { result } = renderHook(() => useCandidateNavigation(embedded({ position: 2 })), {
      wrapper: stableWrapper(),
    });
    expect(result.current).toMatchObject({ total: 3, hasPrev: true, hasNext: true });
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("przejście za granicę strony pobiera następną i otwiera właściwą osobę", async () => {
    apiGet.mockResolvedValue(page([{ id: 20 }], 3, 2, 1));
    const onNavigate = vi.fn();
    const { result } = renderHook(
      () =>
        useCandidateNavigation(
          embedded({ position: 1, pageItems: [{ id: 10 }], pageSize: 1 }, onNavigate),
        ),
      { wrapper: stableWrapper() },
    );

    act(() => result.current.goNext());
    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith({ candidateId: 20, position: 2 }));
    const config = apiGet.mock.calls[0]?.[1] as { params: Record<string, unknown> };
    expect(config.params).toMatchObject({ page: 2, page_size: 1 });
    expect(result.current.error).toBeNull();
  });

  it("pusta strona sąsiednia (lista się skurczyła) — bez nawigacji i bez błędu", async () => {
    apiGet.mockResolvedValue(page([], 1, 2, 1));
    const onNavigate = vi.fn();
    const { result } = renderHook(
      () =>
        useCandidateNavigation(
          embedded({ position: 1, pageItems: [{ id: 10 }], pageSize: 1 }, onNavigate),
        ),
      { wrapper: stableWrapper() },
    );

    act(() => result.current.goNext());
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(1));
    await act(async () => {});
    expect(onNavigate).not.toHaveBeenCalled();
    expect(result.current.error).toBeNull();
  });

  it("bez `pageSize` liczy strony po 20 (pozycja 21 to już strona 2)", async () => {
    apiGet.mockResolvedValue(page([{ id: 30 }], 25, 2));
    const onNavigate = vi.fn();
    const items = Array.from({ length: 20 }, (_, i) => ({ id: i + 1 }));
    const { result } = renderHook(
      () =>
        useCandidateNavigation(
          embedded({ position: 20, pageItems: items, total: 25, pageSize: undefined }, onNavigate),
        ),
      { wrapper: stableWrapper() },
    );

    act(() => result.current.goNext());
    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith({ candidateId: 30, position: 21 }));
    const config = apiGet.mock.calls[0]?.[1] as { params: Record<string, unknown> };
    expect(config.params).toMatchObject({ page: 2, page_size: 20 });
  });

  it("pierwsza pozycja: goPrev i K nic nie robią", () => {
    const onNavigate = vi.fn();
    const { result } = renderHook(
      () => useCandidateNavigation(embedded({ position: 1 }, onNavigate)),
      { wrapper: stableWrapper() },
    );
    expect(result.current.hasPrev).toBe(false);
    act(() => result.current.goPrev());
    press({ key: "k" });
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("pozycja za końcem skurczonej listy: „poprzedni” nie wychodzi poza listę", () => {
    const onNavigate = vi.fn();
    const { result } = renderHook(
      () => useCandidateNavigation(embedded({ position: 6 }, onNavigate)),
      { wrapper: stableWrapper() },
    );
    expect(result.current).toMatchObject({ hasPrev: true, hasNext: false });
    act(() => result.current.goPrev());
    expect(onNavigate).not.toHaveBeenCalled();
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("skróty z modyfikatorem, inne klawisze i pusty `key` są ignorowane", () => {
    const onNavigate = vi.fn();
    renderHook(() => useCandidateNavigation(embedded({ position: 2 }, onNavigate)), {
      wrapper: stableWrapper(),
    });

    press({ key: "j", metaKey: true });
    press({ key: "j", ctrlKey: true });
    press({ key: "k", altKey: true });
    press({ key: "J", shiftKey: true });
    press({ key: "x" });
    press({ key: "" });
    expect(onNavigate).not.toHaveBeenCalled();

    press({ key: "J" });
    expect(onNavigate).toHaveBeenCalledWith({ candidateId: 12, position: 3 });
  });

  it("textarea i contenteditable też blokują skróty", () => {
    const onNavigate = vi.fn();
    renderHook(() => useCandidateNavigation(embedded({ position: 2 }, onNavigate)), {
      wrapper: stableWrapper(),
    });

    const textarea = document.createElement("textarea");
    document.body.appendChild(textarea);
    textarea.focus();
    press({ key: "j" });
    textarea.remove();

    const editable = document.createElement("div");
    editable.contentEditable = "true";
    editable.tabIndex = 0;
    document.body.appendChild(editable);
    editable.focus();
    Object.defineProperty(editable, "isContentEditable", { value: true });
    press({ key: "k" });
    editable.remove();

    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("po odmontowaniu klawisze nie nawigują", () => {
    const onNavigate = vi.fn();
    const { unmount } = renderHook(
      () => useCandidateNavigation(embedded({ position: 2 }, onNavigate)),
      { wrapper: stableWrapper() },
    );
    unmount();
    press({ key: "j" });
    expect(onNavigate).not.toHaveBeenCalled();
  });
});
