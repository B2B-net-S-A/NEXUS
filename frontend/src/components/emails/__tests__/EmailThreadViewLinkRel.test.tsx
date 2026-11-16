import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import DOMPurify from "dompurify";

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

// Pentest 13.11.2026: link z `target` w treści maila otwierał kartę z dostępem
// do `window.opener` (reverse tabnabbing) — DOMPurify zostawiał `target`, ale
// nie dopisywał `rel`.
function renderMail(bodyHtml: string) {
  const mail = {
    id: 1,
    m365_conversation_id: "c1",
    subject: "Oferta",
    from_address: "obcy@example.com",
    from_name: "Obcy nadawca",
    to_addresses: [],
    cc_addresses: [],
    body_html: bodyHtml,
    body_text: "",
    body_preview: "",
    sent_at: "2026-11-13T10:00:00Z",
    received_at: "2026-11-13T10:00:00Z",
    direction: "received",
    has_attachments: false,
    is_read: true,
    is_private_filtered: false,
    send_state: null,
    attachments: [],
  };
  listThreadMessages.mockResolvedValue({ data: [mail] });
  getEmail.mockResolvedValue({ data: mail });
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

describe("EmailThreadView: linki z treści maila", () => {
  it("link z target dostaje rel=noopener noreferrer", async () => {
    renderMail('<p><a href="https://example.com/x" target="_blank">kliknij</a></p>');

    const link = await screen.findByRole("link", { name: "kliknij" });
    expect(link).toHaveAttribute("target", "_blank");
    const rel = (link.getAttribute("rel") ?? "").split(/\s+/);
    expect(rel).toEqual(expect.arrayContaining(["noopener", "noreferrer"]));
  });

  it("rel z maila nie zostawia otwartej furtki (opener)", async () => {
    renderMail('<a href="https://example.com/y" target="_blank" rel="opener">tu</a>');

    const link = await screen.findByRole("link", { name: "tu" });
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("hook nie zostaje na globalnym DOMPurify dla innych ekranów", async () => {
    renderMail('<a href="https://example.com/z" target="_blank">z</a>');
    await screen.findByRole("link", { name: "z" });

    const html = DOMPurify.sanitize('<a href="https://example.com" target="_blank">a</a>', {
      ADD_ATTR: ["target"],
    });
    expect(html).not.toContain("rel=");
  });
});
