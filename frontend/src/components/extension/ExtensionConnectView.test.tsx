/**
 * Strona „Połącz wtyczkę z NEXUSEM” (28.10.2026): klucz idzie do wtyczki
 * przez `chrome.runtime.sendMessage`, nigdy do adresu. Dane fikcyjne.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const connect = vi.fn();
vi.mock("@/lib/api", () => ({
  linkedinExtensionApi: { connect: (...args: unknown[]) => connect(...args) },
}));

import { ExtensionConnectView } from "./ExtensionConnectView";

const EXT_ID = "abcdefghijklmnopabcdefghijklmnop";

beforeEach(() => {
  connect.mockReset();
});

describe("ExtensionConnectView", () => {
  it("wydaje klucz i oddaje go wtyczce, potem mówi, jako kto połączono", async () => {
    connect.mockResolvedValue({
      data: {
        key: "nxe_v1_x",
        user: { id: 1, name: "Ola Testowa", initials: "OT" },
        expires_at: "2027-04-26T10:00:00Z",
        api_base: "https://api.example.test",
        frontend_url: "https://nexus.example.test",
      },
    });
    const send = vi.fn().mockResolvedValue(undefined);

    render(<ExtensionConnectView extensionId={EXT_ID} extensionVersion="1.0.0" send={send} ping={async () => true} />);

    expect(await screen.findByText(/Połączono jako/)).toBeInTheDocument();
    expect(screen.getByText("Ola Testowa")).toBeInTheDocument();
    expect(connect).toHaveBeenCalledWith({ extension_id: EXT_ID, extension_version: "1.0.0" });
    expect(send).toHaveBeenCalledWith(EXT_ID, {
      type: "nexus-extension-key",
      key: "nxe_v1_x",
      apiBase: "https://api.example.test",
      frontUrl: "https://nexus.example.test",
    });
  });

  it("bez id wtyczki nie wydaje klucza i mówi, skąd otworzyć stronę", () => {
    render(<ExtensionConnectView extensionId={null} extensionVersion={null} send={vi.fn()} ping={async () => true} />);
    expect(screen.getByText(/Tę stronę otwiera wtyczka NEXUS/)).toBeInTheDocument();
    expect(connect).not.toHaveBeenCalled();
  });

  it("id spoza formatu Chrome traktuje jak brak wtyczki", () => {
    render(<ExtensionConnectView extensionId="../evil" extensionVersion={null} send={vi.fn()} ping={async () => true} />);
    expect(connect).not.toHaveBeenCalled();
  });

  it("gdy wtyczka nie odbierze klucza, pokazuje błąd i pozwala ponowić", async () => {
    connect.mockResolvedValue({
      data: {
        key: "k",
        user: { id: 1, name: "Ola", initials: "O" },
        expires_at: "",
        api_base: "",
        frontend_url: "",
      },
    });
    const send = vi
      .fn()
      .mockRejectedValueOnce(new Error("extension_rejected"))
      .mockResolvedValueOnce(undefined);

    render(<ExtensionConnectView extensionId={EXT_ID} extensionVersion={null} send={send} ping={async () => true} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Wtyczka nie odebrała połączenia");
    await userEvent.click(screen.getByRole("button", { name: "Połącz ponownie" }));
    await waitFor(() => expect(screen.getByText(/Połączono jako/)).toBeInTheDocument());
    expect(connect).toHaveBeenCalledTimes(2);
  });

  it("odmowa serwera (obca wtyczka) pokazuje zdanie z API", async () => {
    connect.mockRejectedValue({
      isAxiosError: true,
      response: { status: 403, data: { detail: "Ta wtyczka nie jest wtyczką NEXUSA." } },
    });
    render(<ExtensionConnectView extensionId={EXT_ID} extensionVersion={null} send={vi.fn()} ping={async () => true} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Ta wtyczka nie jest wtyczką NEXUSA.");
  });
});

describe("ExtensionConnectView — bez wtyczki", () => {
  it("nie prosi NEXUSA o klucz, gdy wtyczka nie odpowiada (nie odłącza działającej)", async () => {
    render(
      <ExtensionConnectView extensionId={EXT_ID} extensionVersion={null} send={vi.fn()} ping={async () => false} />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie widzę wtyczki NEXUS");
    expect(connect).not.toHaveBeenCalled();
  });
});
