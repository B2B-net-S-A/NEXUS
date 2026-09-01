import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({
  push: vi.fn(),
  params: { current: new URLSearchParams() },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: nav.push, replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => nav.params.current,
  usePathname: () => "/insights",
}));

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ default: mocks, api: mocks }));

import { RekrutacjaPanel } from "@/components/insights/RekrutacjaPanel";

beforeAll(() => {
  window.matchMedia = ((q: string) => ({
    matches: false,
    media: q,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});

function mount() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <RekrutacjaPanel />
    </QueryClientProvider>,
  );
}

describe("tmp all-time round-trip", () => {
  it("klik Wszystko -> URL -> stan przycisku", async () => {
    mocks.get.mockRejectedValue(
      Object.assign(new Error("HTTP 500"), { response: { status: 500 } }),
    );
    mount();
    const grp1 = await screen.findByRole("group", { name: "Granulacja okresu" });
    const all = Array.from(grp1.querySelectorAll("button")).find(
      (b) => b.textContent === "Wszystko",
    )!;
    await userEvent.click(all);
    console.log("PUSHED:", JSON.stringify(nav.push.mock.calls));

    nav.params.current = new URLSearchParams(
      String(nav.push.mock.calls[0][0]).split("?")[1],
    );
    cleanup();
    mount();
    const grp2 = await screen.findByRole("group", { name: "Granulacja okresu" });
    console.log(
      "PRESSED:",
      JSON.stringify(
        Array.from(grp2.querySelectorAll("button")).map((b) => [
          b.textContent,
          b.getAttribute("aria-pressed"),
        ]),
      ),
    );
    console.log(
      "EXPORT_BTN_PRESENT:",
      String(!!screen.queryByText(/Eksportuj/)),
    );
    expect(true).toBe(true);
  });
});
