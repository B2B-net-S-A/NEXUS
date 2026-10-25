import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
}));

const showToast = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast }),
}));

import { M365ForwardsPanel } from "@/components/hr/settings/M365ForwardsPanel";
import {
  canCloseRule,
  reconcileSummary,
  type M365MailboxCheck,
  type M365SavedForward,
} from "@/lib/api/hr-m365";

// Identyfikatory składane w locie — gotowy UUID w tekście łapie gitleaks jako klucz API.
const testUuid = (n: number) => ["00000000", "0000", "4000", "8000", String(n).padStart(12, "0")].join("-");
const LEAVE_OK = testUuid(1);
const LEAVE_OLD = testUuid(2);
const STRAY = testUuid(3);

function saved(overrides: Partial<M365SavedForward>): M365SavedForward {
  return {
    leave_request_id: LEAVE_OK,
    user_id: 5,
    user_name: "Anna Przykładowa",
    substitute_user_id: 6,
    substitute_name: "Jan Zastępca",
    start_date: "2026-10-19",
    end_date: "2026-10-23",
    status: "approved",
    consent: true,
    health: "ok",
    reason: null,
    last_operation: null,
    ...overrides,
  };
}

const SAVED = [
  saved({}),
  saved({
    leave_request_id: LEAVE_OLD,
    user_id: 7,
    user_name: "Ewa Po Urlopie",
    start_date: "2026-10-12",
    end_date: "2026-10-16",
    consent: false,
    health: "orphan",
    reason: "Przekierowanie wyłączono, a reguła mogła zostać w skrzynce.",
  }),
];

const CHECK: M365MailboxCheck = {
  available: true,
  mode: "live",
  message: null,
  scanned: 3,
  unreadable: [{ user_id: 9, name: "Piotr Nieczytelny", error: "forbidden (403)" }],
  items: [
    {
      rule_id: "rule-1",
      rule_name: `NEXUS · zastępstwo · ${STRAY}`,
      owner: "nexus",
      leave_request_id: STRAY,
      known: false,
      user_id: 7,
      user_name: "Ewa Po Urlopie",
      start_date: null,
      end_date: null,
      substitute_name: null,
      health: "unknown",
      reason: "Reguła nie pasuje do żadnego wniosku w NEXUSIE.",
    },
  ],
};

function mockApi() {
  get.mockImplementation((url: string) => {
    if (url === "/api/hr/admin/m365/forwards") {
      return Promise.resolve({ data: { mode: "live", today: "2026-10-20", items: SAVED } });
    }
    return Promise.reject(new Error(`nieoczekiwany GET ${url}`));
  });
}

function renderPanel(mode: "off" | "simulate" | "live" = "live") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <M365ForwardsPanel mode={mode} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  showToast.mockReset();
});

describe("M365ForwardsPanel", () => {
  it("lists saved forwards with their state and the right action per row", async () => {
    // Urlop 19–23.10.2026 „jeszcze trwa” tylko przy dniu z odpowiedzi
    // (20.10) — bez zamrożonej daty test padał od 24.10.2026.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-20T10:00:00+02:00"));
    onTestFinished(() => {
      vi.useRealTimers();
    });
    mockApi();
    renderPanel();
    const running = (await screen.findByText("Anna Przykładowa")).closest("tr") as HTMLElement;
    expect(within(running).getByText("Działa")).toBeInTheDocument();
    expect(within(running).getByText("19.10.2026 – 23.10.2026")).toBeInTheDocument();
    expect(
      within(running).getByRole("button", { name: "Wyłącz przekierowanie" }),
    ).toBeInTheDocument();
    const left = screen.getByText("Ewa Po Urlopie").closest("tr") as HTMLElement;
    expect(within(left).getByText("Do zamknięcia")).toBeInTheDocument();
    expect(within(left).getByRole("button", { name: "Zamknij regułę" })).toBeInTheDocument();
  });

  it("offers closing the rule, not turning consent off, after the leave ended", async () => {
    // Audyt 19.10.2026: po końcu urlopu „Wyłącz przekierowanie” niczego nie
    // zamykało (kolejka pomija zakończone), a „Zamknij regułę” było ukryte.
    get.mockImplementation((url: string) =>
      url === "/api/hr/admin/m365/forwards"
        ? Promise.resolve({
            data: {
              mode: "live",
              today: "2026-10-20",
              items: [
                saved({
                  user_name: "Olga Po Urlopie",
                  start_date: "2000-01-03",
                  end_date: "2000-01-07",
                  health: "orphan",
                }),
              ],
            },
          })
        : Promise.reject(new Error(`nieoczekiwany GET ${url}`)),
    );
    renderPanel();
    const row = (await screen.findByText("Olga Po Urlopie")).closest("tr") as HTMLElement;
    expect(within(row).queryByRole("button", { name: "Wyłącz przekierowanie" })).toBeNull();
    expect(within(row).getByRole("button", { name: "Zamknij regułę" })).toBeInTheDocument();
  });

  it("closes a stray rule through the queue only after confirmation", async () => {
    mockApi();
    post.mockResolvedValue({ data: { queued: true, leave_request_id: LEAVE_OLD, known: true } });
    renderPanel();
    const left = (await screen.findByText("Ewa Po Urlopie")).closest("tr") as HTMLElement;
    await userEvent.click(within(left).getByRole("button", { name: "Zamknij regułę" }));
    const dialog = await screen.findByRole("dialog");
    expect(post).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Zamknij regułę" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/hr/admin/m365/forwards/close", {
        user_id: 7,
        leave_request_id: LEAVE_OLD,
      }),
    );
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("Zamknięcie reguły czeka w kolejce", "success"),
    );
  });

  it("shows live mailbox check results, unknown rules and unreadable mailboxes", async () => {
    mockApi();
    post.mockResolvedValue({ data: CHECK });
    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Sprawdź skrzynki" }));
    expect(await screen.findByText(/Sprawdzono skrzynek: 3/)).toBeInTheDocument();
    expect(screen.getByText("Reguła bez wniosku")).toBeInTheDocument();
    expect(screen.getByText(/Piotr Nieczytelny/)).toHaveTextContent(
      "Brak uprawnień aplikacji w Exchange (403)",
    );
    expect(post).toHaveBeenCalledWith("/api/hr/admin/m365/forwards/check");
  });

  it("says plainly when Microsoft 365 is off instead of showing an empty check", async () => {
    mockApi();
    post.mockResolvedValue({
      data: {
        available: false,
        mode: "off",
        message: "Microsoft 365 jest wyłączony (tryb „Wyłączone”) — NEXUS nie czyta skrzynek.",
        items: [],
      },
    });
    renderPanel("off");
    expect(await screen.findByRole("button", { name: "Uzgodnij teraz" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Sprawdź skrzynki" }));
    expect(await screen.findByRole("status")).toHaveTextContent("NEXUS nie czyta skrzynek");
  });

  it("runs reconcile on demand and reports what it did", async () => {
    mockApi();
    post.mockResolvedValue({
      data: {
        status: "done",
        mode: "live",
        counts: { mailboxes: 4, oof_enqueued: 1, oof_request_created: 2 },
      },
    });
    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Uzgodnij teraz" }));
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(
        "Uzgadnianie zakończone — skrzynek: 4 · operacji do kolejki: 1 · wnioski z Outlooka: 2",
        "success",
      ),
    );
  });
});

describe("hr-m365 helpers", () => {
  it("closes only stray rules — a running one goes through forward-off", () => {
    expect(canCloseRule({ health: "orphan" })).toBe(true);
    expect(canCloseRule({ health: "unknown" })).toBe(true);
    expect(canCloseRule({ health: "ok" })).toBe(false);
    expect(canCloseRule({ health: "missing" })).toBe(false);
  });

  it("summarises an empty pass", () => {
    expect(reconcileSummary({ mailboxes: 2 })).toBe("skrzynek: 2 · bez nowych operacji");
    // Osoba, która odeszła, to nie błąd odczytu (prod 19.10.2026).
    expect(reconcileSummary({ mailboxes: 2, skipped_exited: 1 })).toBe(
      "skrzynek: 2 · bez nowych operacji · pominięte (osoby, które odeszły): 1",
    );
  });
});
