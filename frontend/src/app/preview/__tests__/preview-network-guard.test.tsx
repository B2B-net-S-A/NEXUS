/**
 * Runda 10 (R10-N10-2): harness `/preview/*` nie wysyła zapisów do API i nie
 * używa tokenu oglądającego.
 *
 * Do 27.09.2026 checkbox w `/preview/dl-alerts` w zalogowanej przeglądarce
 * wołał `POST /api/dl-alerts/101/handled` i zamykał prawdziwą sprawę DL.
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import type { AxiosAdapter, AxiosResponse, InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { api } from "@/lib/api";

const sent: InternalAxiosRequestConfig[] = [];
const fakeAdapter: AxiosAdapter = async (config) => {
  sent.push(config);
  return {
    data: {},
    status: 200,
    statusText: "OK",
    headers: {},
    config,
  } as AxiosResponse;
};
const fetchCalls: Array<{ input: unknown; init?: RequestInit }> = [];

beforeAll(() => {
  // Adapter i fetch podmieniamy PRZED pierwszym włączeniem blokady — blokada
  // opakowuje to, co zastanie.
  api.defaults.adapter = fakeAdapter;
  window.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    fetchCalls.push({ input, init });
    return new Response("{}", { status: 200 });
  }) as typeof window.fetch;
});

afterEach(() => {
  sent.length = 0;
  fetchCalls.length = 0;
});

async function loadLayout() {
  return (await import("../layout")).default;
}

function methodOf(config: InternalAxiosRequestConfig): string {
  return (config.method ?? "get").toLowerCase();
}

function authOf(config: InternalAxiosRequestConfig): unknown {
  const headers = config.headers as { get?: (n: string) => unknown; Authorization?: unknown };
  return typeof headers?.get === "function" ? headers.get("Authorization") : headers?.Authorization;
}

describe("layout /preview blokuje zapisy", () => {
  it("odrzuca zapis axios bez wysyłki, odczyt idzie bez Authorization", async () => {
    const PreviewLayout = await loadLayout();
    const view = render(
      <PreviewLayout>
        <p>harness</p>
      </PreviewLayout>,
    );

    await expect(api.post("/api/dl-alerts/101/handled")).rejects.toMatchObject({
      code: "ECONNABORTED",
    });
    await expect(api.delete("/api/clients/1/orders/1")).rejects.toMatchObject({
      code: "ECONNABORTED",
    });
    await api.get("/api/whatever", {
      headers: { Authorization: "Bearer token-ogladajacego" },
    });

    expect(sent.map(methodOf)).toEqual(["get"]);
    expect(authOf(sent[0])).toBeFalsy();

    view.unmount();
    // Po wyjściu z /preview ruch wraca do normy.
    await api.post("/api/cokolwiek");
    expect(sent.map(methodOf)).toEqual(["get", "post"]);
  });

  it("odrzuca zapis przez fetch, odczyt fetch bez Authorization", async () => {
    const PreviewLayout = await loadLayout();
    const view = render(
      <PreviewLayout>
        <p>harness</p>
      </PreviewLayout>,
    );
    await expect(
      window.fetch("/api/x", { method: "POST", body: "{}" }),
    ).rejects.toBeInstanceOf(TypeError);
    await window.fetch("/preview/plik.pdf", {
      headers: { Authorization: "Bearer token-ogladajacego" },
    });
    expect(fetchCalls).toHaveLength(1);
    const headers = new Headers(fetchCalls[0].init?.headers);
    expect(headers.get("Authorization")).toBeNull();
    view.unmount();
  });

  it("klik w checkbox harnessu /preview/dl-alerts nie wysyła zapisu", async () => {
    const PreviewLayout = await loadLayout();
    const DlAlertsPreview = (await import("../dl-alerts/page")).default;
    render(
      <ToastProvider>
        <PreviewLayout>
          <DlAlertsPreview />
        </PreviewLayout>
      </ToastProvider>,
    );
    const boxes = await screen.findAllByRole("checkbox");
    expect(boxes.length).toBeGreaterThan(0);
    await act(async () => {
      fireEvent.click(boxes[0]);
    });
    // Mutacja startuje po `cancelQueries` w `onMutate` — dajmy jej dobiec.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 100));
    });
    expect(sent.filter((config) => methodOf(config) !== "get")).toEqual([]);
  }, 20_000);
});
