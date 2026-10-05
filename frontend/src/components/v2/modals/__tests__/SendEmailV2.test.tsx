/**
 * Jedno okno maila (D5, 04.10.2026): bez podłączonej skrzynki Microsoft 365
 * okno mówi, co zrobić, zamiast kończyć wysyłkę błędem 412.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getConnection = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({
  microsoft365Api: { getConnection },
}));
vi.mock("@/components/emails/EmailCompose", () => ({
  default: () => <div role="dialog" aria-label="Nowy email" />,
}));

import { SendEmailV2, mailboxUnavailable } from "../SendEmailV2";

function renderWindow(email = "jan@example.com") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SendEmailV2
        open
        onOpenChange={vi.fn()}
        candidateId={7}
        candidateName="Jan Kowalski"
        candidateEmail={email}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("SendEmailV2", () => {
  it("z podłączoną skrzynką otwiera kompozytor Microsoft 365", async () => {
    getConnection.mockResolvedValue({ data: { connected: true } });
    renderWindow();
    expect(await screen.findByRole("dialog", { name: "Nowy email" })).toBeInTheDocument();
  });

  it("bez skrzynki pokazuje drogę do Ustawień i adres do programu pocztowego", async () => {
    getConnection.mockResolvedValue({ data: { connected: false } });
    renderWindow();
    expect(
      await screen.findByRole("heading", {
        name: "Twoja skrzynka Microsoft 365 nie jest podłączona",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Podłącz w Ustawieniach" })).toHaveAttribute(
      "href",
      "/settings?area=me&item=outlook",
    );
    expect(screen.getByRole("link", { name: /Program pocztowy/ })).toHaveAttribute(
      "href",
      "mailto:jan@example.com",
    );
    expect(screen.getByText(/nie zapisze się w historii kandydata/)).toBeInTheDocument();
  });

  it("awaria odczytu stanu skrzynki nie blokuje — kompozytor pokaże błąd wysyłki", async () => {
    getConnection.mockRejectedValue(new Error("500"));
    renderWindow();
    expect(await screen.findByRole("dialog", { name: "Nowy email" })).toBeInTheDocument();
  });
});

describe("mailboxUnavailable", () => {
  it("skrzynka do ponownego połączenia też nie wyśle maila", () => {
    expect(mailboxUnavailable({ connected: true, requires_reconnect: true })).toBe(true);
    expect(mailboxUnavailable({ connected: true })).toBe(false);
    expect(mailboxUnavailable(undefined)).toBe(false);
  });
});
