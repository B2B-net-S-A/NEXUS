/**
 * Notatki w doku rekrutacji = ta sama lista co w „Historii” profilu
 * (29.09.2026): odpowiedzi pod notatką, przypięte pierwsze, notatki
 * automatów za „Pokaż systemowe (N)”.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
  apiPatch: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => mocks.apiGet(...a),
    post: (...a: unknown[]) => mocks.apiPost(...a),
    delete: (...a: unknown[]) => mocks.apiDelete(...a),
    patch: (...a: unknown[]) => mocks.apiPatch(...a),
  },
  extractErrorMsg: () => "Błąd",
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/hooks/useMentionableUsers", () => ({
  useMentionableUsers: () => ({ data: [] }),
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (sel: (s: { user: { id: number; role: string } }) => unknown) =>
    sel({ user: { id: 5, role: "recruiter" } }),
  hasRole: () => false,
}));

import { DockNotesPanel } from "@/components/v2/jobs/workbench-chrome";

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

const items = [
  {
    id: 1,
    content: "Nie dzwonić przed 10.",
    author_id: 6,
    author_name: "Kamil W.",
    created_at: "2026-09-28T10:00:00Z",
    pinned_at: "2026-09-28T11:00:00Z",
    job_id: 10,
    job_title: "Java Dev",
    replies: [
      {
        id: 7,
        content: "Potwierdzone z kandydatem.",
        author_id: 5,
        author_name: "Ola Nowak",
        created_at: "2026-09-28T12:00:00Z",
        parent_note_id: 1,
        replies: [],
      },
    ],
  },
  {
    id: 2,
    content: "Auto-match 70/100 — dodany automatycznie.",
    author_id: null,
    author_name: null,
    created_at: "2026-09-20T10:00:00Z",
    external_source: "system",
    is_system: true,
    job_id: 10,
    replies: [],
  },
];

beforeEach(() => {
  mocks.apiGet.mockReset();
  mocks.apiPost.mockReset();
  mocks.apiGet.mockResolvedValue({ data: { items, total: 2 } });
  mocks.apiPost.mockResolvedValue({ data: {} });
});

describe("DockNotesPanel — lista jak w profilu", () => {
  it("pokazuje odpowiedzi pod notatką i chowa systemowe za przełącznikiem", async () => {
    wrap(<DockNotesPanel candidateId={42} jobId={10} readOnly={false} />);

    expect(await screen.findByText("Potwierdzone z kandydatem.")).toBeTruthy();
    expect(mocks.apiGet).toHaveBeenCalledWith("/api/notes?candidate_id=42&job_id=10");
    expect(screen.getByRole("article", { name: "Przypięta notatka" })).toBeTruthy();
    // Lista jednej rekrutacji — bez plakietki rekrutacji na każdej notatce.
    expect(screen.queryByText("Java Dev")).toBeNull();

    expect(screen.queryByText(/Auto-match 70\/100/)).toBeNull();
    fireEvent.click(screen.getByLabelText("Pokaż systemowe (1)"));
    expect(screen.getByText(/Auto-match 70\/100/)).toBeTruthy();
  });

  it("odpowiedź idzie na trasę notatek z notatką główną", async () => {
    wrap(<DockNotesPanel candidateId={42} jobId={10} readOnly={false} />);
    const thread = await screen.findByRole("article", { name: "Przypięta notatka" });
    fireEvent.click(within(thread).getByRole("button", { name: "Odpowiedz na notatkę" }));
    fireEvent.change(screen.getByLabelText("Treść odpowiedzi"), {
      target: { value: "Dzięki!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Odpowiedz" }));
    await waitFor(() =>
      expect(mocks.apiPost).toHaveBeenCalledWith("/api/notes", {
        parent_note_id: 1,
        content: "Dzięki!",
        note_type: "general",
      }),
    );
  });

  it("tylko do odczytu: bez przypinania i odpowiedzi", async () => {
    wrap(<DockNotesPanel candidateId={42} jobId={10} readOnly />);
    await screen.findByText("Potwierdzone z kandydatem.");
    expect(screen.queryByRole("button", { name: /Przypnij|Odepnij/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Odpowiedz na notatkę" })).toBeNull();
  });
});
