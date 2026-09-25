import type { AnchorHTMLAttributes } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// „Dodaj do puli”: awaria pobrania pul NIE może wyglądać jak „Brak pul” —
// rekruter zakładał wtedy drugą pulę o tej samej nazwie.

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

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/candidates",
}));

// Lista kandydatów ciągnie podgląd CV (pdf.js) — tu niepotrzebny.
vi.mock("@/lib/pdfjs-loader", () => ({ loadPdfJs: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, default: { ...original.default, get: vi.fn() } };
});

import api from "@/lib/api";
import { BulkAddToPoolModal } from "@/components/v2/pages/CandidatesListV2";

const get = vi.mocked(api.get);

function renderModal() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BulkAddToPoolModal
        selectedCount={2}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
        pending={false}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
});

describe("BulkAddToPoolModal", () => {
  it("shows the failure with a retry, never „Brak pul”", async () => {
    const user = userEvent.setup();
    get.mockRejectedValueOnce({ response: { status: 500 } });
    renderModal();

    expect(
      await screen.findByText(/Nie udało się pobrać listy pul/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Brak pul/)).not.toBeInTheDocument();

    get.mockResolvedValueOnce({
      data: [{ id: 3, name: "Java seniorzy", candidate_count: 12 }],
    });
    await user.click(screen.getByRole("button", { name: /Spróbuj ponownie/i }));
    expect(await screen.findByText("Java seniorzy")).toBeInTheDocument();
  });

  it("says there are no pools only after a successful empty answer", async () => {
    get.mockResolvedValueOnce({ data: [] });
    renderModal();
    expect(
      await screen.findByText(/Nie ma jeszcze żadnej puli/),
    ).toBeInTheDocument();
  });
});
