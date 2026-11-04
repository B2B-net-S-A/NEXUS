import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { plainTextToHtml } from "@/components/emails/EmailCompose";
import { applyStreamEvent, type JarvisTurnState } from "@/lib/jarvis/reducer";
import type { JarvisMailDraft } from "@/lib/jarvis/types";
import { JarvisMailDraftCard } from "../JarvisMailDraftCard";

const opened = vi.fn();
vi.mock("@/components/v2/modals/SendEmailV2", () => ({
  SendEmailV2: (props: { open: boolean; candidateEmail: string; defaultSubject?: string; defaultBody?: string }) => {
    if (props.open) opened(props);
    return null;
  },
}));

let quickView: { candidate?: { name?: string; lastname?: string; email?: string | null } } = {};
vi.mock("@/lib/api", () => ({ api: { get: async () => ({ data: quickView }) } }));

const DRAFT: JarvisMailDraft = {
  candidate_id: 7,
  candidate_name: "Ola Przykładowa",
  email: "ola@example.com",
  subject: "Aktualne CV",
  body: "Dzień dobry,\nczy może Pani przesłać CV?",
};

describe("szkic maila od Jarvisa", () => {
  beforeEach(() => {
    opened.mockReset();
    quickView = {};
  });

  it("treść od modelu trafia do okna jako tekst, nie HTML", () => {
    expect(plainTextToHtml("A <b>x</b> & \"y\"\n\nB")).toBe(
      "<p>A &lt;b&gt;x&lt;/b&gt; &amp; &quot;y&quot;</p><p>B</p>",
    );
    expect(plainTextToHtml("linia 1\nlinia 2")).toBe("<p>linia 1<br>linia 2</p>");
    expect(plainTextToHtml("")).toBe("");
  });

  it("mówi, że nic nie wysłano, i otwiera okno maila z tematem i treścią", () => {
    render(<JarvisMailDraftCard draft={DRAFT} />);
    expect(screen.getByText(/nic nie wysłano/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Otwórz w oknie maila/ }));
    expect(opened).toHaveBeenCalledWith(
      expect.objectContaining({ candidateEmail: "ola@example.com", defaultSubject: "Aktualne CV", defaultBody: DRAFT.body }),
    );
  });

  it("szkic z historii doczytuje adres przy otwarciu", async () => {
    quickView = { candidate: { name: "Ola", lastname: "Przykładowa", email: "ola@example.com" } };
    render(<JarvisMailDraftCard draft={{ candidate_id: 7, subject: "Temat", body: "Treść" }} />);
    expect(screen.getByText("Kandydat #7")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Otwórz w oknie maila/ }));
    await waitFor(() => expect(opened).toHaveBeenCalled());
  });

  it("brak adresu w profilu mówi to zamiast otwierać okno", async () => {
    quickView = { candidate: { name: "Ola", email: null } };
    render(<JarvisMailDraftCard draft={{ candidate_id: 7, subject: "Temat", body: "Treść" }} />);
    fireEvent.click(screen.getByRole("button", { name: /Otwórz w oknie maila/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("nie ma adresu");
    expect(opened).not.toHaveBeenCalled();
  });

  it("zdarzenie strumienia dokłada kartę szkicu", () => {
    const start: JarvisTurnState = { items: [], thinking: true, mood: "working", conversationId: null };
    expect(applyStreamEvent(start, { type: "mail_draft", draft: DRAFT }).items).toEqual([
      { kind: "mail_draft", draft: DRAFT },
    ]);
  });
});
