/**
 * `/wypis/{token}`: GET niczego nie zmienia (skanery linków w poczcie), wypis
 * dopiero po kliknięciu — zwykły `fetch` na publiczne API, bez sesji.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UnsubscribeConfirm } from "../UnsubscribeConfirm";

const fetchMock = vi.fn();

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

describe("UnsubscribeConfirm", () => {
  it("wypisuje dopiero po kliknięciu i mówi, że obowiązkowe dalej przychodzą", async () => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ unsubscribed: true }), { status: 200 }));
    const user = userEvent.setup();
    render(<UnsubscribeConfirm token="tok_123" unsubscribed={false} />);

    expect(fetchMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Wypisz mnie" }));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/public\/consultant-mail\/unsubscribe\/tok_123$/);
    expect(init).toMatchObject({ method: "POST" });
    expect(await screen.findByText(/Wypisano/)).toBeInTheDocument();
    expect(screen.getByText(/obowiązkowe/)).toBeInTheDocument();
  });

  it("już wypisany nie widzi przycisku", () => {
    render(<UnsubscribeConfirm token="tok_123" unsubscribed />);
    expect(screen.queryByRole("button", { name: "Wypisz mnie" })).not.toBeInTheDocument();
    expect(screen.getByText(/już wypisany/)).toBeInTheDocument();
  });

  it("błąd serwera to komunikat przy przycisku, nie pusta strona", async () => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "Link nieprawidłowy lub wygasły." }), { status: 404 }),
    );
    const user = userEvent.setup();
    render(<UnsubscribeConfirm token="tok_123" unsubscribed={false} />);
    await user.click(screen.getByRole("button", { name: "Wypisz mnie" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Link nieprawidłowy lub wygasły.");
    expect(screen.getByRole("button", { name: "Wypisz mnie" })).toBeEnabled();
  });
});
