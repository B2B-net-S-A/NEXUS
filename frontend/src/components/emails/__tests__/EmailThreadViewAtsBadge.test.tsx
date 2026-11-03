import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

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

const BADGE = "Wysłane z ATS";

function message(id: number, fields: Record<string, unknown>) {
  return {
    id,
    m365_conversation_id: "c1",
    subject: "Rozmowa o projekcie",
    from_address: "rekruter@example.com",
    from_name: `Nadawca ${id}`,
    to_addresses: [],
    cc_addresses: [],
    body_html: null,
    body_text: "Treść wiadomości",
    body_preview: "Treść wiadomości",
    sent_at: `2026-10-12T10:0${id}:00Z`,
    received_at: `2026-10-12T10:0${id}:00Z`,
    direction: "sent",
    has_attachments: false,
    is_read: true,
    is_private_filtered: false,
    send_state: null,
    sent_from_nexus: false,
    attachments: [],
    ...fields,
  };
}

const card = (id: number) =>
  screen.getByText(`Nadawca ${id}`).closest("div.rounded-lg") as HTMLElement;

// Sync M365 zapisuje w `emails` także pocztę wysłaną wprost z Outlooka, więc
// sam kierunek „sent” nie mówi, skąd mail wyszedł.
describe("EmailThreadView: plakietka „Wysłane z ATS”", () => {
  it("jest tylko na mailu wysłanym z NEXUSA", async () => {
    const messages = [
      message(1, {}),
      message(2, { sent_from_nexus: true, send_state: "sent" }),
      message(3, { direction: "received" }),
    ];
    listThreadMessages.mockResolvedValue({ data: messages });
    getEmail.mockImplementation((id: number) =>
      Promise.resolve({ data: messages.find((m) => m.id === id) }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <EmailThreadView
          candidateId={42}
          candidateEmail="kandydat@example.com"
          conversationId="c1"
          onClose={() => {}}
        />
      </QueryClientProvider>,
    );

    await screen.findByText("Nadawca 1");
    expect(within(card(1)).queryByText(BADGE)).not.toBeInTheDocument();
    expect(within(card(2)).getByText(BADGE)).toBeInTheDocument();
    expect(within(card(3)).queryByText(BADGE)).not.toBeInTheDocument();
  });
});
