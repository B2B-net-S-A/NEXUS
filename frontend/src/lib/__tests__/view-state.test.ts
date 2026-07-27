import { describe, expect, it } from "vitest"

import {
  httpStatusFromError,
  isBlockingViewState,
  isForbiddenError,
  isNotFoundError,
  resolveViewState,
  type ViewState,
} from "@/lib/view-state"

/** Kształt błędu axios — tylko to, co czyta helper. */
const axiosError = (status: number) => ({
  isAxiosError: true,
  response: { status },
})

describe("httpStatusFromError", () => {
  it("czyta status z odpowiedzi axios", () => {
    expect(httpStatusFromError(axiosError(403))).toBe(403)
    expect(httpStatusFromError(axiosError(500))).toBe(500)
  })

  it("czyta status z płaskiego obiektu błędu (fetch/Response-like)", () => {
    expect(httpStatusFromError({ status: 404 })).toBe(404)
  })

  it("zwraca undefined dla błędu sieci i wartości nie-obiektowych", () => {
    expect(httpStatusFromError(new Error("Network Error"))).toBeUndefined()
    expect(httpStatusFromError(null)).toBeUndefined()
    expect(httpStatusFromError(undefined)).toBeUndefined()
    expect(httpStatusFromError("boom")).toBeUndefined()
    expect(httpStatusFromError({ response: { status: "403" } })).toBeUndefined()
  })
})

describe("isForbiddenError / isNotFoundError", () => {
  it("rozpoznaje 403 i 404, odrzuca resztę", () => {
    expect(isForbiddenError(axiosError(403))).toBe(true)
    expect(isForbiddenError(axiosError(404))).toBe(false)
    expect(isNotFoundError(axiosError(404))).toBe(true)
    expect(isNotFoundError(axiosError(403))).toBe(false)
    expect(isForbiddenError(new Error("Network Error"))).toBe(false)
  })
})

describe("resolveViewState — mapowanie statusu HTTP na stan widoku", () => {
  const cases: Array<{
    name: string
    input: Parameters<typeof resolveViewState>[0]
    expected: ViewState
  }> = [
    {
      name: "pierwsze ładowanie wygrywa ze wszystkim",
      input: { isLoading: true, isError: true, error: axiosError(500), isEmpty: true },
      expected: "loading",
    },
    {
      name: "403 → forbidden (NIE empty)",
      input: { isLoading: false, isError: true, error: axiosError(403), isEmpty: true },
      expected: "forbidden",
    },
    {
      name: "404 → not_found",
      input: { isLoading: false, isError: true, error: axiosError(404), isEmpty: true },
      expected: "not_found",
    },
    {
      name: "500 → error (NIE empty, NIE not_found)",
      input: { isLoading: false, isError: true, error: axiosError(500), isEmpty: true },
      expected: "error",
    },
    {
      name: "502 → error",
      input: { isLoading: false, isError: true, error: axiosError(502), isEmpty: true },
      expected: "error",
    },
    {
      name: "błąd sieci bez statusu → error",
      input: { isLoading: false, isError: true, error: new Error("Network Error") },
      expected: "error",
    },
    {
      name: "isError bez obiektu błędu → error",
      input: { isLoading: false, isError: true },
      expected: "error",
    },
    {
      name: "sukces + 0 rekordów → empty",
      input: { isLoading: false, isError: false, isEmpty: true },
      expected: "empty",
    },
    {
      name: "sukces + rekordy → ready",
      input: { isLoading: false, isError: false, isEmpty: false },
      expected: "ready",
    },
    {
      name: "sukces bez informacji o pustce → ready",
      input: { isLoading: false },
      expected: "ready",
    },
  ]

  for (const { name, input, expected } of cases) {
    it(name, () => {
      expect(resolveViewState(input)).toBe(expected)
    })
  }

  it("regresja F-20: 403 NIGDY nie renderuje się jako pusty wynik", () => {
    for (const status of [401, 403, 404, 409, 422, 500, 502, 503]) {
      const state = resolveViewState({
        isLoading: false,
        isError: true,
        error: axiosError(status),
        isEmpty: true,
      })
      expect(state).not.toBe("empty")
      expect(state).not.toBe("ready")
    }
  })
})

describe("isBlockingViewState", () => {
  it("blokujące są tylko forbidden / not_found / error", () => {
    expect(isBlockingViewState("forbidden")).toBe(true)
    expect(isBlockingViewState("not_found")).toBe(true)
    expect(isBlockingViewState("error")).toBe(true)
    expect(isBlockingViewState("empty")).toBe(false)
    expect(isBlockingViewState("ready")).toBe(false)
    expect(isBlockingViewState("loading")).toBe(false)
  })
})
