/**
 * Historia profilu: zakładka na każdy rodzaj notatki (03.10.2026).
 *
 * Decyzja: nic nie znika — „nie odbiera”, wpisy Delivery Leada, maile
 * i automat mają własne zakładki z licznikami z serwera, a „Rozmowy”
 * zostają czyste. „Nie odebrał” zapisuje próbę kontaktu jednym kliknięciem.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGet = vi.fn();
const apiPost = vi.fn();
const showInfo = vi.fn();
const showError = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a: unknown[]) => apiGet(...a), post: (...a: unknown[]) => apiPost(...a) },
  callsApi: { getForCandidate: vi.fn(async () => []) },
  extractErrorMsg: () => "Błąd serwera",
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError, showInfo, showSuccess: vi.fn() }),
}));
vi.mock("@/lib/celebrate", () => ({ celebrate: vi.fn() }));
vi.mock("@/hooks/useMentionableUsers", () => ({
  useMentionableUsers: () => ({ data: [] }),
}));
vi.mock("@/components/v2/forms/MentionTextarea", () => ({
  MentionTextarea: ({
    value,
    onChange,
    ariaLabel,
  }: {
    value: string;
    onChange: (v: string) => void;
    ariaLabel: string;
  }) => <textarea aria-label={ariaLabel} value={value} onChange={(e) => onChange(e.target.value)} />,
}));
vi.mock("@/components/emails/EmailThreadList", () => ({
  default: () => <div>skrzynka M365</div>,
}));
vi.mock("@/components/calls/CallsTimeline", () => ({ default: () => <div>połączenia</div> }));
vi.mock("@/components/v2/pages/CandidateChatTab", () => ({ default: () => <div>czat</div> }));
vi.mock("@/components/v2/files/FilePreviewModal", () => ({
  FilePreviewContent: () => null,
  downloadDocumentBlob: vi.fn(),
}));
vi.mock("@/components/v2/screening/RecommendationCardDialog", () => ({
  RecommendationCardDialog: ({ jobId }: { jobId: number }) => (
    <div role="dialog" aria-label="Karta rekomendacji">
      karta rekrutacji {jobId}
    </div>
  ),
}));

import { HistoryTab } from "@/components/v2/candidate-profile/HistoryTab";
import type { CandidateActivityView } from "@/components/v2/pages/candidate-profile-navigation";
import { useAuthStore } from "@/store/auth";

const note = (id: number, group: string, content: string, extra: object = {}) => ({
  id,
  group,
  content,
  author_id: 5,
  author_name: "Marta Testowa",
  created_at: "2026-09-28T09:00:00Z",
  job_id: null,
  replies: [],
  ...extra,
});

const NOTES = [
  note(1, "talks", "Szuka projektu z Javą 21."),
  note(2, "talks", "Stawka 135 zł/h, dostępność 1 miesiąc.", { job_id: 10, job_title: "Java Dev" }),
  note(3, "contact", "nie odbiera"),
  note(4, "delivery", "Dopisz do CV projekt bankowy."),
  note(5, "email", "Od: kandydat@example.com Temat: CV"),
  note(6, "automat", "Auto-match 71/100", { is_system: true, author_name: null }),
];

function respond(groupCounts: Record<string, number>) {
  apiGet.mockImplementation((url: string) =>
    Promise.resolve(
      url.includes("/recommendation-cards")
        ? {
            data: {
              candidate_id: 42,
              facts: [],
              conversations: [],
              note_links: [
                {
                  note_id: 2,
                  job_id: 10,
                  job_title: "Java Dev",
                  fields: ["rate", "availability"],
                  field_labels: ["Stawka", "Dostępność"],
                  answers: 0,
                },
              ],
            },
          }
        : { data: { items: NOTES, total: NOTES.length, group_counts: groupCounts } },
    ),
  );
}

function Harness({ initial = "notes" as CandidateActivityView, readOnly = false }) {
  const [view, setView] = useState<CandidateActivityView>(initial);
  return (
    <HistoryTab
      candidateId={42}
      candidate={{ name: "Tomasz", lastname: "Wzorcowy", email: null, cv_filename: null }}
      activityView={view}
      onActivityViewChange={setView}
      timeline={{ items: [], isPending: false, error: null, refetch: vi.fn() }}
      recruitments={[]}
      defaultJobId={null}
      readOnly={readOnly}
      canModerate={false}
      currentUserId={5}
      viewers={[]}
      setPresenceEditing={vi.fn()}
      focusedNoteId={null}
      composeRequest={0}
      onComposeHandled={vi.fn()}
    />
  );
}

function renderTab(props: Parameters<typeof Harness>[0] = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Harness {...props} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: { id: 5, role: "recruiter" } } as never);
  respond({ talks: 40, contact: 3, delivery: 1, email: 1, automat: 9 });
  apiPost.mockResolvedValue({ data: { id: 99 } });
});

describe("Historia — zakładki notatek po rodzaju", () => {
  it("zakładki niosą liczniki z serwera, a „Rozmowy” pokazują tylko notatki z rozmów", async () => {
    renderTab();

    const tabs = screen.getByRole("tablist", { name: "Filtr historii" });
    // Licznik z serwera (40), nie z pobranej listy (2).
    expect(await within(tabs).findByRole("tab", { name: "Rozmowy · 40" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(within(tabs).getByRole("tab", { name: "Próby kontaktu · 3" })).toBeTruthy();
    expect(within(tabs).getByRole("tab", { name: "Delivery Lead · 1" })).toBeTruthy();
    expect(within(tabs).getByRole("tab", { name: "Maile · 1" })).toBeTruthy();
    expect(within(tabs).getByRole("tab", { name: "Automat · 9" })).toBeTruthy();
    // Rejestr połączeń nie nazywa się już „Rozmowy”.
    expect(within(tabs).getByRole("tab", { name: /^Telefony/ })).toBeTruthy();

    expect(screen.getByText("Szuka projektu z Javą 21.")).toBeTruthy();
    expect(screen.queryByText("nie odbiera")).toBeNull();
    expect(screen.queryByText("Dopisz do CV projekt bankowy.")).toBeNull();
    expect(screen.queryByText(/Auto-match/)).toBeNull();
  });

  it("nic nie znika: każdy rodzaj wpisu jest w swojej zakładce", async () => {
    const user = userEvent.setup();
    renderTab();
    const tabs = screen.getByRole("tablist", { name: "Filtr historii" });
    await within(tabs).findByRole("tab", { name: "Rozmowy · 40" });

    await user.click(within(tabs).getByRole("tab", { name: "Próby kontaktu · 3" }));
    expect(screen.getByText("nie odbiera")).toBeTruthy();
    expect(screen.queryByText("Szuka projektu z Javą 21.")).toBeNull();

    await user.click(within(tabs).getByRole("tab", { name: "Delivery Lead · 1" }));
    expect(screen.getByText("Dopisz do CV projekt bankowy.")).toBeTruthy();

    // Automat: wpis systemowy widać od razu, bez „Pokaż systemowe”.
    await user.click(within(tabs).getByRole("tab", { name: "Automat · 9" }));
    expect(screen.getByText(/Auto-match 71\/100/)).toBeTruthy();
    expect(screen.queryByLabelText(/Pokaż systemowe/)).toBeNull();

    // Maile: skrzynka M365 i maile zapisane w notatkach razem.
    await user.click(within(tabs).getByRole("tab", { name: "Maile · 1" }));
    expect(screen.getByText("skrzynka M365")).toBeTruthy();
    expect(screen.getByText("Maile zapisane w notatkach")).toBeTruthy();
    expect(screen.getByText(/Temat: CV/)).toBeTruthy();
  });

  it("„Nie odebrał” zapisuje próbę kontaktu jednym kliknięciem i nie rusza wpisywanej notatki", async () => {
    const user = userEvent.setup();
    renderTab();
    await screen.findByRole("tab", { name: "Rozmowy · 40" });
    const field = screen.getByRole("textbox", { name: "Treść nowej notatki" });
    await user.type(field, "W trakcie pisania");

    await user.click(screen.getByRole("button", { name: "Nie odebrał" }));

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith("/api/notes", {
        candidate_id: 42,
        content: "Nie odebrał.",
        note_type: "general",
        kind: "contact_attempt",
      }),
    );
    expect(showInfo).toHaveBeenCalledWith("Zapisano próbę kontaktu.");
    expect(field).toHaveValue("W trakcie pisania");
  });

  it("notatka, która zasiliła kartę rekomendacji, otwiera tę kartę", async () => {
    const user = userEvent.setup();
    renderTab();
    await screen.findByText("Stawka 135 zł/h, dostępność 1 miesiąc.");

    expect(await screen.findByText("Do karty trafiło: stawka i dostępność.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Karta rekomendacji z tej rozmowy" }));
    expect(screen.getByRole("dialog", { name: "Karta rekomendacji" })).toHaveTextContent(
      "karta rekrutacji 10",
    );
  });

  it("podgląd tylko do odczytu nie ma kompozytora ani „Nie odebrał”", async () => {
    renderTab({ readOnly: true });
    await screen.findByRole("tab", { name: "Rozmowy · 40" });
    expect(screen.queryByRole("button", { name: "Nie odebrał" })).toBeNull();
  });
});
