import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatThreadList } from "@/lib/api/chatNotifications";
import {
  CHAT_TOAST_QUIET_MS,
  chatNotifyMessage,
  shouldShowChatToast,
} from "@/lib/chat-notify";
import { CHAT_NOTIFY_EVENT, type ChatNotifyEvent } from "@/types/job-chat";

const push = vi.hoisted(() => vi.fn());
const showActionToast = vi.hoisted(() => vi.fn());
const apiMock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
const chatOnScreen = vi.hoisted(() => ({ value: false }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showActionToast }),
}));
vi.mock("@/lib/api", () => ({ api: apiMock }));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: { id: 5, authorization_version: 1 } }),
}));
vi.mock("@/lib/active-chat", () => ({
  isChatOnScreen: () => chatOnScreen.value,
}));

import { ChatNotificationsDropdown } from "../ChatNotificationsDropdown";

const NOTE_LINK = "/candidates/3?tab=activity&activity=notes&note=11";

const THREADS: ChatThreadList = {
  unread_threads: 3,
  items: [
    {
      kind: "note",
      entity_id: 11,
      title: "Ewa Lis",
      subtitle: "Kasia W. oznaczył(a) Cię w notatce",
      unread_count: 1,
      has_mention: true,
      last_author_name: null,
      last_message: "@Piotr sprawdź stawkę przed wysyłką",
      last_at: new Date().toISOString(),
      link: NOTE_LINK,
    },
    {
      kind: "job",
      entity_id: 7,
      title: "Tester automatyzujący",
      subtitle: "Bank Przykładowy",
      unread_count: 3,
      has_mention: true,
      last_author_name: "Anna Przykładowa",
      last_message: "Zerkniesz na CV?",
      last_at: new Date().toISOString(),
      link: "/jobs/7?tab=chat&msg=31",
    },
    {
      kind: "candidate",
      entity_id: 9,
      title: "Bartek Testowy",
      subtitle: null,
      unread_count: 1,
      has_mention: false,
      last_author_name: "Celina Fikcyjna",
      last_message: "Oddzwonił, pasuje mu środa.",
      last_at: new Date().toISOString(),
      link: "/candidates/9?tab=chat&msg=44",
    },
    {
      kind: "job",
      entity_id: 8,
      title: "Analityk danych",
      subtitle: "Klient Alfa",
      unread_count: 0,
      has_mention: false,
      last_author_name: "Dawid Wzorcowy",
      last_message: "Dzięki!",
      last_at: new Date().toISOString(),
      link: "/jobs/8?tab=chat&msg=12",
    },
  ],
};

function renderDropdown() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ChatNotificationsDropdown />
    </QueryClientProvider>,
  );
}

// Pierwszy render (Radix, zapytanie) bywa wolniejszy niż domyślna sekunda
// `findBy*` na obciążonym runnerze — stąd własny budżet oczekiwania.
function findTrigger(name: string | RegExp = /^Wiadomości/) {
  return screen.findByRole("button", { name }, { timeout: 5_000 });
}

function notify(detail: Partial<ChatNotifyEvent> = {}) {
  const event: ChatNotifyEvent = {
    kind: "job",
    entity_id: 7,
    notification_type: "job_chat_message",
    link: "/jobs/7?tab=chat&msg=32",
    thread_title: "Tester automatyzujący",
    author_name: "Anna Przykładowa",
    preview: "Jest odpowiedź od klienta",
    ...detail,
  };
  act(() => {
    window.dispatchEvent(new CustomEvent(CHAT_NOTIFY_EVENT, { detail: event }));
  });
  return event;
}

beforeEach(() => {
  push.mockReset();
  showActionToast.mockReset();
  apiMock.get.mockReset();
  apiMock.put.mockReset();
  apiMock.get.mockResolvedValue({ data: THREADS });
  apiMock.put.mockResolvedValue({ data: { success: true, updated: 1 } });
  chatOnScreen.value = false;
});

describe("ChatNotificationsDropdown", () => {
  it("licznik na ikonie to liczba rozmów z nowymi wiadomościami", async () => {
    renderDropdown();
    const button = await findTrigger("Wiadomości — rozmowy z nowymi wiadomościami: 3");
    expect(button).toHaveTextContent("3");
    // Okienko „Wiadomości” prosi też o wątki notatek (16.10.2026).
    expect(apiMock.get).toHaveBeenCalledWith("/api/notifications/chats", {
      params: { include_notes: true },
    });
  });

  it("pokazuje jedną pozycję na rozmowę: nazwa, klient, autor i fragment", async () => {
    renderDropdown();
    fireEvent.click(await findTrigger());

    const job = await screen.findByRole("button", {
      name: "Czat rekrutacji: Tester automatyzujący — nowe wiadomości: 3, oznaczono Cię",
    });
    expect(job).toHaveTextContent("Czat rekrutacji · Bank Przykładowy");
    expect(job).toHaveTextContent("Anna Przykładowa: Zerkniesz na CV?");
    expect(job).toHaveTextContent("wzmianka");
    expect(
      screen.getByRole("button", {
        name: "Czat kandydata: Bartek Testowy — nowe wiadomości: 1",
      }),
    ).toBeInTheDocument();
    // Rozmowa bez nowych wiadomości zostaje na liście, bez licznika.
    expect(
      screen.getByRole("button", { name: "Czat rekrutacji: Analityk danych" }),
    ).toBeInTheDocument();
  });

  it("klik gasi powiadomienia rozmowy i prowadzi do wiadomości", async () => {
    renderDropdown();
    fireEvent.click(await findTrigger());
    fireEvent.click(
      await screen.findByRole("button", { name: /Czat kandydata: Bartek Testowy/ }),
    );

    expect(push).toHaveBeenCalledWith("/candidates/9?tab=chat&msg=44");
    await waitFor(() =>
      expect(apiMock.put).toHaveBeenCalledWith("/api/notifications/chats/read", {
        kind: "candidate",
        entity_id: 9,
      }),
    );
  });

  it("wzmianka w notatce to osobny wątek, który klik gasi po linku", async () => {
    renderDropdown();
    fireEvent.click(await findTrigger());
    const note = await screen.findByRole("button", {
      name: "Notatka: Ewa Lis — nowe wiadomości: 1, oznaczono Cię",
    });
    expect(note).toHaveTextContent("Kasia W. oznaczył(a) Cię w notatce");
    expect(note).toHaveTextContent("@Piotr sprawdź stawkę przed wysyłką");

    fireEvent.click(note);
    expect(push).toHaveBeenCalledWith(NOTE_LINK);
    await waitFor(() =>
      expect(apiMock.put).toHaveBeenCalledWith("/api/notifications/chats/read", {
        kind: "note",
        link: NOTE_LINK,
      }),
    );
  });

  it("„Oznacz wszystkie” gasi wszystkie rozmowy naraz", async () => {
    renderDropdown();
    fireEvent.click(await findTrigger());
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Oznacz wszystkie jako przeczytane",
      }),
    );
    await waitFor(() =>
      expect(apiMock.put).toHaveBeenCalledWith(
        "/api/notifications/chats/read",
        undefined,
        { params: { include_notes: true } },
      ),
    );
  });

  it("awaria nie wygląda jak brak rozmów", async () => {
    apiMock.get.mockRejectedValue(new Error("503"));
    renderDropdown();
    fireEvent.click(screen.getByRole("button", { name: "Wiadomości" }));

    expect(
      await screen.findByText("Nie udało się wczytać rozmów."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Nie masz wiadomości/)).not.toBeInTheDocument();

    apiMock.get.mockResolvedValue({ data: { items: [], unread_threads: 0 } });
    fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
    expect(
      await screen.findByText("Nie masz wiadomości z ostatnich 30 dni."),
    ).toBeInTheDocument();
  });

  it("nowa wiadomość daje dymek z „Otwórz”, który prowadzi do wiadomości", async () => {
    renderDropdown();
    await findTrigger();
    const event = notify();

    expect(showActionToast).toHaveBeenCalledTimes(1);
    const [message, options] = showActionToast.mock.calls[0];
    expect(message).toBe(chatNotifyMessage(event));
    expect(options.actionLabel).toBe("Otwórz");

    act(() => {
      options.onAction();
    });
    expect(push).toHaveBeenCalledWith("/jobs/7?tab=chat&msg=32");
  });

  it("wzmianka w notatce daje dymek zawsze, nawet przy otwartym czacie", async () => {
    chatOnScreen.value = true;
    renderDropdown();
    await findTrigger();
    notify({
      kind: "note",
      entity_id: 0,
      notification_type: "note_mention",
      link: NOTE_LINK,
      thread_title: "Kasia W. oznaczył(a) Cię w notatce",
      author_name: "",
      preview: "@Piotr sprawdź stawkę",
    });
    expect(showActionToast).toHaveBeenCalledTimes(1);
    expect(showActionToast.mock.calls[0][0]).toBe(
      "Kasia W. oznaczył(a) Cię w notatce: @Piotr sprawdź stawkę",
    );
  });

  it("nie pokazuje dymka, gdy ten czat jest właśnie na ekranie", async () => {
    chatOnScreen.value = true;
    renderDropdown();
    await findTrigger();
    notify();
    expect(showActionToast).not.toHaveBeenCalled();
  });
});

describe("dymek czatu — treść i wyciszanie serii", () => {
  const base: ChatNotifyEvent = {
    kind: "job",
    entity_id: 7,
    notification_type: "job_chat_message",
    link: "/jobs/7?tab=chat&msg=1",
    thread_title: "Tester automatyzujący",
    author_name: "Anna Przykładowa",
    preview: "Jest odpowiedź",
  };

  it("nazywa rozmowę i autora, a wzmiankę mówi wprost", () => {
    expect(chatNotifyMessage(base)).toBe(
      "Anna Przykładowa w czacie „Tester automatyzujący”: Jest odpowiedź",
    );
    expect(
      chatNotifyMessage({
        ...base,
        kind: "candidate",
        notification_type: "job_chat_mention",
        thread_title: "Bartek Testowy",
        preview: "",
      }),
    ).toBe("Anna Przykładowa oznaczył(a) Cię w czacie kandydata „Bartek Testowy”");
  });

  it("zwykła wiadomość z tej samej rozmowy najwyżej raz na okno ciszy; wzmianka zawsze", () => {
    const shown = new Map<string, number>();
    expect(shouldShowChatToast(base, shown, 1_000)).toBe(true);
    expect(shouldShowChatToast(base, shown, 1_000 + CHAT_TOAST_QUIET_MS - 1)).toBe(false);
    expect(shouldShowChatToast({ ...base, entity_id: 8 }, shown, 2_000)).toBe(true);
    expect(
      shouldShowChatToast({ ...base, notification_type: "job_chat_mention" }, shown, 3_000),
    ).toBe(true);
    expect(shouldShowChatToast(base, shown, 3_000 + CHAT_TOAST_QUIET_MS)).toBe(true);
  });

  it("notatka nie podlega oknu ciszy", () => {
    const shown = new Map<string, number>();
    const note: ChatNotifyEvent = {
      ...base,
      kind: "note",
      entity_id: 0,
      notification_type: "note_reply",
    };
    expect(shouldShowChatToast(note, shown, 1_000)).toBe(true);
    expect(shouldShowChatToast(note, shown, 1_001)).toBe(true);
  });
});
