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

const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, post },
    default: { ...original.default, get: vi.fn() },
  };
});

import api from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { BulkAddToPoolModal } from "@/components/v2/pages/CandidatesListV2";

const get = vi.mocked(api.get);

function renderModal(onConfirm = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BulkAddToPoolModal
        selectedCount={2}
        onCancel={vi.fn()}
        onConfirm={onConfirm}
        pending={false}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  useAuthStore.setState({ user: null });
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

  it("puts my lists first and creates a new private list for the selection", async () => {
    const user = userEvent.setup();
    useAuthStore.setState({
      user: { id: 7, name: "Anna Przykładowa", email: "anna@example.com", role: "recruiter" } as never,
    });
    get.mockResolvedValueOnce({
      data: [
        { id: 3, name: "Java seniorzy", candidate_count: 12 },
        { id: 5, name: "Moja lista", candidate_count: 1, is_personal: true, owner_id: 7 },
      ],
    });
    post.mockResolvedValueOnce({ data: { id: 21, name: "Na styczeń" } });
    const onConfirm = vi.fn();
    renderModal(onConfirm);

    await screen.findByText("Moja lista");
    const names = screen
      .getAllByRole("button")
      .map((b) => b.textContent ?? "")
      .filter((t) => /Moja lista|Java seniorzy/.test(t));
    expect(names[0]).toMatch(/Moja lista/);
    expect(screen.getByText("Moje listy")).toBeInTheDocument();
    expect(screen.getByText("Pule i listy zespołu")).toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: "Nazwa nowej listy" }), "Na styczeń");
    await user.click(screen.getByRole("button", { name: "Utwórz i dodaj" }));
    expect(post).toHaveBeenCalledWith("/api/talent-pools", {
      name: "Na styczeń",
      is_personal: true,
      team_visible: false,
    });
    expect(onConfirm).toHaveBeenCalledWith(21);
  });
});
