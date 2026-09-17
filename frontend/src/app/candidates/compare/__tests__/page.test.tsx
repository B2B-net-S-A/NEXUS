import type { AnchorHTMLAttributes } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

const apiGet = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => apiGet(...args) },
}));

import CompareCandidatesPage from "../page";

function renderPage() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <CompareCandidatesPage />
    </QueryClientProvider>,
  );
}

describe("/candidates/compare — powrót do listy (UAT B21)", () => {
  beforeEach(() => {
    urlParams = new URLSearchParams();
    // Profile nigdy nie dojeżdżają — testujemy nagłówek, nie karty.
    apiGet.mockReset();
    apiGet.mockImplementation(() => new Promise(() => {}));
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

describe("/candidates/compare — karty profili", () => {
  beforeEach(() => {
    urlParams = new URLSearchParams("ids=1,2");
    apiGet.mockReset();
  });

  it("renderuje tag-obiekt z importu Traffita zamiast wywracać ekran (React #31)", async () => {
    apiGet.mockImplementation((url: string) =>
      Promise.resolve({
        data: {
          id: url.endsWith("/1") ? 1 : 2,
          name: url.endsWith("/1") ? "Anna" : "Jan",
          lastname: "Testowa",
          tags: [
            "java",
            { type: "traffit_source", domain: "Rekomendacja", value: null },
            { type: "traffit_source", domain: "   ", value: null },
          ],
        },
      }),
    );
    renderPage();
    expect(await screen.findByText("Anna Testowa")).toBeInTheDocument();
    expect(screen.getAllByText("Rekomendacja")).toHaveLength(2);
    expect(screen.getAllByText("java")).toHaveLength(2);
  });

  it("403 na jednym profilu daje kartę błędu z „Ponów”, a nagłówek liczy wybrane osoby", async () => {
    let denied = true;
    apiGet.mockImplementation((url: string) => {
      if (url.endsWith("/2") && denied) {
        return Promise.reject({
          isAxiosError: true,
          response: { status: 403, data: { detail: "Brak dostępu do kandydata." } },
        });
      }
      return Promise.resolve({
        data: { id: url.endsWith("/1") ? 1 : 2, name: url.endsWith("/1") ? "Anna" : "Jan", lastname: "Testowa" },
      });
    });
    renderPage();
    expect(await screen.findByText("Anna Testowa")).toBeInTheDocument();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nie udało się pobrać kandydata #2");
    expect(alert).toHaveTextContent("Brak dostępu do kandydata.");
    expect(screen.getByText("(2 kandydatów)")).toBeInTheDocument();

    denied = false;
    await userEvent.click(screen.getByRole("button", { name: "Ponów" }));
    expect(await screen.findByText("Jan Testowa")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });
});
