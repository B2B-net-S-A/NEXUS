import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const listThreadMessages = vi.fn();
const getEmail = vi.fn();
vi.mock("@/lib/api", () => ({
  microsoft365Api: {
    listThreadMessages: (...a: unknown[]) => listThreadMessages(...a),
    getEmail: (...a: unknown[]) => getEmail(...a),
  },
}));
vi.mock("../EmailCompose", () => ({ default: () => null }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError: () => {} }) }));

import EmailThreadView from "../EmailThreadView";

const LOADING = "Wczytuję wiadomość...";
const INVITE_REPLY = "Odpowiedź na zaproszenie, bez treści";
const NO_CONTENT = "Ta wiadomość nie ma treści.";

function message(id: number, fields: Record<string, unknown> = {}) {
  return {
    id,
    m365_conversation_id: "c1",
    subject: "Rozmowa o projekcie",
    from_address: "rekruter@example.com",
    from_name: `Nadawca ${id}`,
    to_addresses: [],
    cc_addresses: [],
    body_html: null,
    body_text: "",
    body_preview: "",
    sent_at: `2026-10-12T10:0${id}:00Z`,
    received_at: `2026-10-12T10:0${id}:00Z`,
    direction: "sent",
    has_attachments: false,
    is_read: true,
    is_private_filtered: false,
    send_state: null,
    attachments: [],
    ...fields,
  };
}

function renderThread(messages: ReturnType<typeof message>[]) {
  listThreadMessages.mockResolvedValue({ data: messages });
  getEmail.mockImplementation((id: number) =>
    Promise.resolve({ data: messages.find((m) => m.id === id) }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <EmailThreadView
        candidateId={42}
        candidateEmail="kandydat@example.com"
        conversationId="c1"
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );
}

const card = (id: number) =>
  screen.getByText(`Nadawca ${id}`).closest("div.rounded-lg") as HTMLElement;

describe("EmailThreadView: wiadomość bez treści", () => {
  beforeEach(() => {
    listThreadMessages.mockReset();
    getEmail.mockReset();
  });

  it("pusta odpowiedź na zaproszenie nie wisi na „Wczytuję” i nie udaje maila z ATS", async () => {
    renderThread([message(1, { subject: "Accepted: Rozmowa o projekcie" })]);

    await waitFor(() => expect(getEmail).toHaveBeenCalled());
    expect(await screen.findByText(INVITE_REPLY)).toBeInTheDocument();
    expect(screen.queryByText(LOADING)).not.toBeInTheDocument();
    expect(within(card(1)).queryByText("Wysłane z ATS")).not.toBeInTheDocument();
    expect(within(card(1)).queryByRole("button", { name: "Odpowiedz" })).not.toBeInTheDocument();
  });

  it("otwiera ostatnią wiadomość z treścią, a tytuł bierze z niej", async () => {
    renderThread([
      message(1, { body_text: "Treść rozmowy", body_preview: "Treść rozmowy" }),
      message(2, { subject: "Canceled: Rozmowa o projekcie" }),
    ]);

    expect(await screen.findByRole("heading", { name: "Rozmowa o projekcie" })).toBeInTheDocument();
    expect(await within(card(1)).findByText("Treść rozmowy", { selector: "pre" })).toBeInTheDocument();
    expect(within(card(2)).getByText(INVITE_REPLY)).toBeInTheDocument();
    expect(screen.queryByText(LOADING)).not.toBeInTheDocument();
  });

  it("zwykła pusta wiadomość mówi, że nie ma treści, i można na nią odpowiedzieć", async () => {
    renderThread([message(1, { subject: "Re: Rozmowa", direction: "received" })]);

    expect(await screen.findByText(NO_CONTENT)).toBeInTheDocument();
    expect(within(card(1)).getByRole("button", { name: "Odpowiedz" })).toBeInTheDocument();
  });

  it("w trakcie wczytywania pokazuje „Wczytuję”", async () => {
    renderThread([message(1)]);
    getEmail.mockImplementation(() => new Promise(() => {}));

    expect(await screen.findByText(LOADING)).toBeInTheDocument();
  });

  it("awaria wczytania nie wygląda jak brak treści", async () => {
    renderThread([message(1)]);
    getEmail.mockImplementation(() => Promise.reject(new Error("500")));

    expect(await screen.findByText("Nie udało się wczytać wiadomości.")).toBeInTheDocument();
    expect(screen.queryByText(NO_CONTENT)).not.toBeInTheDocument();
  });
});
