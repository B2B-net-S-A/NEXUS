/**
 * INT-04/05 — okno wysyłki nadaje JEDEN `client_request_id` przy otwarciu
 * i powtarza go przy ponowieniu. Serwer rozpoznaje po nim ponowienie i nie
 * wysyła drugiego maila; nowe okno to nowa wiadomość (nowy identyfikator).
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { newClientRequestId } from "@/lib/client-request-id";

const state = vi.hoisted(() => ({
  html: "<p>Treść</p>",
  compose: [] as Array<Record<string, unknown>>,
  reply: [] as Array<Record<string, unknown>>,
  failFirst: true,
}));

vi.mock("@tiptap/react", () => {
  const editor = {
    commands: { setContent: vi.fn() },
    getHTML: () => state.html,
    on: vi.fn(),
    off: vi.fn(),
  };
  return {
    useEditor: () => editor,
    EditorContent: () => <div data-testid="editor" />,
  };
});
vi.mock("@tiptap/starter-kit", () => ({ default: {} }));

vi.mock("@/lib/api", () => ({
  microsoft365Api: {
    compose: vi.fn(async (_id: number, payload: Record<string, unknown>) => {
      state.compose.push(payload);
      if (state.failFirst && state.compose.length === 1) {
        throw Object.assign(new Error("Network Error"), { response: undefined });
      }
      return { data: { id: 1 } };
    }),
    reply: vi.fn(async (_id: number, payload: Record<string, unknown>) => {
      state.reply.push(payload);
      return { data: { id: 2 } };
    }),
  },
  userEmailTemplatesApi: {
    list: vi.fn(async () => ({ data: [] })),
    render: vi.fn(),
  },
}));

import EmailCompose from "../EmailCompose";

function renderCompose(props: Record<string, unknown>) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: 0 }, queries: { retry: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <EmailCompose
        candidateId={5}
        candidateName="Anna Test"
        onClose={() => undefined}
        {...(props as { mode: "new"; defaultTo: string })}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  state.compose = [];
  state.reply = [];
  state.failFirst = true;
});

describe("EmailCompose — identyfikator operacji", () => {
  it("ponowienie z tego samego okna wysyła ten sam client_request_id", async () => {
    renderCompose({ mode: "new", defaultTo: "kandydat@example.com" });
    fireEvent.click(screen.getByRole("button", { name: /Wyślij/ }));
    await waitFor(() => expect(state.compose).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: /Wyślij/ }));
    await waitFor(() => expect(state.compose).toHaveLength(2));

    const [first, second] = state.compose;
    expect(typeof first.client_request_id).toBe("string");
    expect(first.client_request_id).toBe(second.client_request_id);
  });

  it("nowe okno to nowy identyfikator", async () => {
    state.failFirst = false;
    const first = renderCompose({ mode: "new", defaultTo: "a@example.com" });
    fireEvent.click(screen.getByRole("button", { name: /Wyślij/ }));
    await waitFor(() => expect(state.compose).toHaveLength(1));
    first.unmount();

    renderCompose({ mode: "new", defaultTo: "a@example.com" });
    fireEvent.click(screen.getByRole("button", { name: /Wyślij/ }));
    await waitFor(() => expect(state.compose).toHaveLength(2));
    expect(state.compose[0].client_request_id).not.toBe(
      state.compose[1].client_request_id,
    );
  });

  it("odpowiedź też niesie identyfikator", async () => {
    renderCompose({
      mode: "reply",
      replyTo: { id: 9, from_address: "k@example.com", subject: "Pytanie" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Wyślij/ }));
    await waitFor(() => expect(state.reply).toHaveLength(1));
    expect(state.reply[0]).toMatchObject({ email_id: 9 });
    expect(state.reply[0].client_request_id).toMatch(/^[A-Za-z0-9-]{8,64}$/);
  });
});

describe("newClientRequestId", () => {
  it("spełnia format walidacji backendu", () => {
    expect(newClientRequestId()).toMatch(/^[A-Za-z0-9-]{8,64}$/);
  });
});
