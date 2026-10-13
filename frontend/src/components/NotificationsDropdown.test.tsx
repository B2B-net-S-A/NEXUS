import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NotificationsDropdown } from "@/components/NotificationsDropdown";
import { notificationsApi } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  notificationsApi: { listForBell: vi.fn(), markRead: vi.fn(), markAllReadForBell: vi.fn() },
}));
const hookState = vi.hoisted(() => ({
  unreadCount: 0,
  clearUnread: vi.fn(),
  options: null as { interviewsInWindow?: boolean } | null,
  hasInterviewsWindow: false,
}));
vi.mock("@/hooks/useNotifications", () => ({
  useNotifications: (options: { interviewsInWindow?: boolean }) => {
    hookState.options = options;
    return {
      unreadCount: hookState.unreadCount,
      clearUnread: hookState.clearUnread,
      wsConnected: true,
    };
  },
}));
vi.mock("@/hooks/useHasInterviewsWindow", () => ({
  useHasInterviewsWindow: () => hookState.hasInterviewsWindow,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector?: (state: unknown) => unknown) => {
    const state = { user: { id: 1, authorization_version: 1 } };
    return selector ? selector(state) : state;
  },
}));
vi.mock("@/components/feedback/InterviewFeedbackModal", () => ({
  InterviewFeedbackModal: () => null,
}));

const listNotifications = vi.mocked(notificationsApi.listForBell);

function makeItems(count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: i + 1,
    user_id: 1,
    title: "Powiadomienie " + (i + 1),
    message: "treść",
    link: null,
    notification_type: "candidate_added",
    is_read: false,
    created_at: "2026-09-01T08:00:00Z",
  }));
}

function mockAvailable(available: number) {
  listNotifications.mockImplementation(async (limit?: number) => ({
    data: { items: makeItems(Math.min(limit ?? 20, available)), unread_count: 0 },
  }) as unknown as Awaited<ReturnType<typeof notificationsApi.listForBell>>);
}

function renderDropdown() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NotificationsDropdown />
    </QueryClientProvider>,
  );
}

// Pozycje listy mają `role="button"` (obsługa klawiatury), więc zapytania po
// roli liczyłyby nazwę dostępną dla 200 wierszy — przyciski stopki szukamy
// po tekście, żeby test nie mierzył wydajności jsdom.
// B51: dzwonek pokazywał 20 pozycji i kończył listę samym „Zamknij" — przy
// liczniku ponad tysiąca nieprzeczytanych starsze były niedostępne.
describe("NotificationsDropdown — „Pokaż więcej”", () => {
  beforeEach(() => {
    listNotifications.mockReset();
  });

  it("doładowuje 20 → 50 → 200 i chowa przycisk, gdy lista się skończy", async () => {
    mockAvailable(60);
    const user = userEvent.setup();
    renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));

    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(20));
    expect(listNotifications).toHaveBeenLastCalledWith(20);

    await user.click(screen.getByText("Pokaż więcej"));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(50));
    expect(listNotifications).toHaveBeenLastCalledWith(50);

    await user.click(screen.getByText("Pokaż więcej"));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(60));
    expect(listNotifications).toHaveBeenLastCalledWith(200);
    // 60 < 200 — to już wszystko: bez przycisku i bez „Pokazano 200".
    expect(screen.queryByText("Pokaż więcej")).toBeNull();
    expect(screen.queryByText(/Pokazano/)).toBeNull();
    expect(screen.getByText("Zamknij")).toBeInTheDocument();
   }, 15_000);

  it("krótsza lista niż limit nie pokazuje „Pokaż więcej”", async () => {
    mockAvailable(5);
    const user = userEvent.setup();
    renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(5));
    expect(screen.queryByText("Pokaż więcej")).toBeNull();
  });

  it("na suficie 200 mówi wprost, że pokazano 200 najnowszych", async () => {
    mockAvailable(1000);
    const user = userEvent.setup();
    renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(20));
    await user.click(screen.getByText("Pokaż więcej"));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(50));
    await user.click(screen.getByText("Pokaż więcej"));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(200));
    expect(screen.queryByText("Pokaż więcej")).toBeNull();
    expect(screen.getByText("Pokazano 200 najnowszych")).toBeInTheDocument();
   }, 15_000);
});

// 10.10.2026, produkcja: „Moje zadania” na pulpicie pytają o powiadomienia
// RAZEM z czatami, a dzwonek bez nich — pod tym samym kluczem zapytania. Dzwonek
// pokazywał wtedy wiersze czatu i licznik z czatami.
describe("NotificationsDropdown — własny klucz zapytania", () => {
  beforeEach(() => {
    listNotifications.mockReset();
  });

  it("nie czyta listy „Moich zadań” z pulpitu (ta zawiera czaty)", async () => {
    mockAvailable(2);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    client.setQueryData(["notifications", "1:1", 20], {
      items: [
        {
          id: 900,
          user_id: 1,
          title: "Anna Testowa: nowa wiadomość",
          message: "treść z czatu",
          link: "/jobs/1?tab=chat&msg=5",
          notification_type: "job_chat_message",
          is_read: false,
          created_at: "2026-09-01T08:00:00Z",
        },
      ],
      unread_count: 337,
    });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={client}>
        <NotificationsDropdown />
      </QueryClientProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));

    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(2));
    expect(listNotifications).toHaveBeenCalledWith(20);
    expect(screen.queryByText("Anna Testowa: nowa wiadomość")).toBeNull();
  });
});

// 13.10.2026: rozmowy u klienta i prepy mają własne okienko w górnym pasku.
describe("NotificationsDropdown — kategoria „Rozmowy” w osobnym okienku", () => {
  beforeEach(() => {
    listNotifications.mockReset();
    vi.mocked(notificationsApi.markAllReadForBell).mockReset();
    vi.mocked(notificationsApi.markAllReadForBell).mockResolvedValue(
      {} as Awaited<ReturnType<typeof notificationsApi.markAllReadForBell>>,
    );
    hookState.hasInterviewsWindow = true;
    window.localStorage.clear();
    return () => {
      hookState.hasInterviewsWindow = false;
    };
  });

  it("osoba z okienkiem: lista, „Oznacz wszystko” i gniazdo pomijają kategorię", async () => {
    listNotifications.mockResolvedValue({
      data: { items: makeItems(2), unread_count: 2, own_unread_count: 2 },
    } as unknown as Awaited<ReturnType<typeof notificationsApi.listForBell>>);
    const user = userEvent.setup();
    renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));

    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(2));
    expect(listNotifications).toHaveBeenCalledWith(20, { excludeInterviews: true });
    expect(hookState.options?.interviewsInWindow).toBe(true);

    await user.click(screen.getByText("Oznacz wszystko jako przeczytane"));
    expect(notificationsApi.markAllReadForBell).toHaveBeenCalledWith({ excludeInterviews: true });
  });

  it("osoba bez okienka widzi rozmowy w dzwonku jak dotąd", async () => {
    hookState.hasInterviewsWindow = false;
    mockAvailable(1);
    const user = userEvent.setup();
    renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));

    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(1));
    expect(listNotifications).toHaveBeenCalledWith(20);
    expect(hookState.options?.interviewsInWindow).toBe(false);
    expect(screen.queryByText(/mają teraz własne okienko/)).toBeNull();
  });

  it("jednorazowa podpowiedź: „Pokaż” otwiera okienko i nie wraca", async () => {
    mockAvailable(1);
    const opened = vi.fn();
    window.addEventListener("nexus:open-interviews-window", opened);
    const user = userEvent.setup();
    const first = renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));
    expect(await screen.findByText(/mają teraz własne okienko/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Pokaż" }));
    expect(opened).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/mają teraz własne okienko/)).toBeNull();
    window.removeEventListener("nexus:open-interviews-window", opened);
    first.unmount();

    renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(1));
    expect(screen.queryByText(/mają teraz własne okienko/)).toBeNull();
  });
});

describe("NotificationsDropdown — dostępność, licznik i ładowanie", () => {
  beforeEach(() => {
    listNotifications.mockReset();
    vi.mocked(notificationsApi.markRead).mockReset();
    vi.mocked(notificationsApi.markRead).mockResolvedValue(
      {} as Awaited<ReturnType<typeof notificationsApi.markRead>>,
    );
    hookState.unreadCount = 0;
    hookState.clearUnread.mockReset();
  });

  it("pozycję da się otworzyć klawiaturą (Enter) — oznacza ją jako przeczytaną", async () => {
    mockAvailable(2);
    const user = userEvent.setup();
    renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));
    const item = await screen.findByRole("button", { name: /Powiadomienie 1\b/ });
    item.focus();
    await user.keyboard("{Enter}");
    expect(notificationsApi.markRead).toHaveBeenCalledWith(1);
  });

  it("przypomnienie w zastępstwie ma etykietę", async () => {
    listNotifications.mockResolvedValue({
      data: {
        items: [{ ...makeItems(1)[0], user_id: 2, on_behalf_of_name: "Anna Nowak" }],
        unread_count: 1,
      },
    } as unknown as Awaited<ReturnType<typeof notificationsApi.listForBell>>);
    const user = userEvent.setup();
    renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));
    expect(await screen.findByText("w zastępstwie za Anna Nowak")).toBeInTheDocument();
  });

  it("powiadomienia o przydziale requestów i „CV gotowe” mają własne ikony, nie zapasowy dzwonek", async () => {
    listNotifications.mockResolvedValue({
      data: {
        items: [
          {
            ...makeItems(1)[0],
            id: 11,
            title: "Propozycje przydziału do akceptacji: 4",
            notification_type: "request_allocation_proposals",
            link: "/dashboard#czeka-na-ciebie",
          },
          {
            ...makeItems(1)[0],
            id: 12,
            title: "Nowy request do pracy",
            notification_type: "request_assignment_changed",
            link: "/jobs/42",
          },
          { ...makeItems(1)[0], id: 13, title: "Typ z przyszłości", notification_type: "not_a_known_type" },
          {
            ...makeItems(1)[0],
            id: 14,
            title: "CV gotowe do sprawdzenia: Anna Nowak",
            notification_type: "cv_ready",
            link: "/jobs/42?candidate=7&panel=cv",
          },
        ],
        unread_count: 4,
      },
    } as unknown as Awaited<ReturnType<typeof notificationsApi.listForBell>>);
    const user = userEvent.setup();
    renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));
    const iconOf = async (title: string) =>
      (await screen.findByText(title)).closest("li")?.querySelector("svg")?.getAttribute("class") ?? "";
    expect(await iconOf("Propozycje przydziału do akceptacji: 4")).toContain("lucide-user-check");
    expect(await iconOf("Nowy request do pracy")).toContain("lucide-list-checks");
    // Nieznany typ dostaje neutralny dzwonek — tak wyglądały oba typy bez wpisu.
    expect(await iconOf("Typ z przyszłości")).toContain("lucide-bell-ring");
    // 14.10.2026: automat CV skończył — ikona dokumentu, nie zapasowy dzwonek.
    expect(await iconOf("CV gotowe do sprawdzenia: Anna Nowak")).toContain("lucide-file-check");
  });

  it("po odświeżeniu listy zeruje deltę z gniazda (bez widmowego licznika)", async () => {
    mockAvailable(1);
    hookState.unreadCount = 7;
    renderDropdown();
    await waitFor(() => expect(hookState.clearUnread).toHaveBeenCalled());
  });

  it("„Pokaż więcej” nie znika w trakcie doładowania", async () => {
    const gate: { release: () => void } = { release: () => undefined };
    listNotifications.mockImplementation(async (limit?: number) => {
      if ((limit ?? 20) > 20) {
        await new Promise<void>((resolve) => {
          gate.release = resolve;
        });
      }
      return {
        data: { items: makeItems(Math.min(limit ?? 20, 60)), unread_count: 0 },
      } as unknown as Awaited<ReturnType<typeof notificationsApi.listForBell>>;
    });
    const user = userEvent.setup();
    renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(20));

    await user.click(screen.getByRole("button", { name: "Pokaż więcej" }));
    const loading = await screen.findByRole("button", { name: "Ładowanie…" });
    expect(loading).toBeDisabled();
    expect(screen.getAllByRole("listitem")).toHaveLength(20);

    gate.release();
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(50));
  });
});
