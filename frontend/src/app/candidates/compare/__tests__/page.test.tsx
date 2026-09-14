import type { AnchorHTMLAttributes } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let urlParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useSearchParams: () => urlParams,
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api", () => ({
  // Profile nigdy nie dojeżdżają — testujemy nagłówek, nie karty.
  default: { get: vi.fn(() => new Promise(() => {})) },
}));

import CompareCandidatesPage from "../page";

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <CompareCandidatesPage />
    </QueryClientProvider>,
  );
}

describe("/candidates/compare — powrót do listy (UAT B21)", () => {
  beforeEach(() => {
    urlParams = new URLSearchParams();
  });

  it("„Wróć do kandydatów” niesie filtry, stronę i zaznaczenie", () => {
    urlParams = new URLSearchParams("ids=1,2,3&q=QA-E2E&page=2");
    renderPage();
    const link = screen.getByRole("link", { name: /Wróć do kandydatów/ });
    const href = link.getAttribute("href") ?? "";
    const [path, qs] = href.split("?");
    expect(path).toBe("/candidates");
    const params = new URLSearchParams(qs);
    expect(params.get("q")).toBe("QA-E2E");
    expect(params.get("page")).toBe("2");
    expect(params.get("sel")).toBe("1,2,3");
    expect(params.get("ids")).toBeNull();
  });

  it("pusty stan (mniej niż 2 osoby) też wraca z kontekstem", () => {
    urlParams = new URLSearchParams("ids=1&q=QA-E2E");
    renderPage();
    const link = screen.getByRole("link", { name: /Wróć do listy kandydatów/ });
    expect(link.getAttribute("href")).toBe("/candidates?q=QA-E2E&sel=1");
  });
});
