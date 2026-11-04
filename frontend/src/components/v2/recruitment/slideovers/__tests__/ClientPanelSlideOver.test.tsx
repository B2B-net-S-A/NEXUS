import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { fictionalAdminTransport } from "@/app/preview/client-panel/fixtures";
import type {
  ClientPanelAdminTransport,
  ClientPanelSettings,
} from "@/lib/api/clientPanelAdmin";

import { ClientPanelSlideOver } from "../ClientPanelSlideOver";
import { renderWithQuery } from "./test-utils";

function renderOpen(ui: ReactElement) {
  return renderWithQuery(<ToastProvider>{ui}</ToastProvider>);
}

const QUIET: Partial<ClientPanelSettings> = { requests_open: 0 };

function transport(
  overrides: Partial<ClientPanelAdminTransport> = {},
  settings: Partial<ClientPanelSettings> = QUIET,
): ClientPanelAdminTransport {
  const base = fictionalAdminTransport();
  return {
    ...base,
    fetchSettings: async () => ({ ...(await base.fetchSettings(7)), ...settings }),
    ...overrides,
  };
}

async function confirmDialog() {
  return screen.findByRole("alertdialog").catch(() => screen.findAllByRole("dialog").then((all) => all.at(-1)!));
}

describe("ClientPanelSlideOver", () => {
  it("zamknięte nie pyta serwera", () => {
    const fetchSettings = vi.fn();
    renderOpen(
      <ClientPanelSlideOver
        open={false}
        onOpenChange={vi.fn()}
        jobId={7}
        transport={transport({ fetchSettings })}
      />,
    );
    expect(fetchSettings).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("otwarte: wyłączniki z serwera, link, zero spraw = zakładka ustawień", async () => {
    renderOpen(
      <ClientPanelSlideOver open onOpenChange={vi.fn()} jobId={7} transport={transport()} />,
    );
    expect(await screen.findByRole("switch", { name: "Panel włączony" })).toBeChecked();
    expect(screen.getByTestId("client-panel-url")).toHaveValue(
      "https://nexus.example.test/k/FIKCYJNYLINK2345?c=fikc-anna",
    );
    expect(screen.getByRole("link", { name: "Zobacz jako klient" })).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
  });

  it("wyłączony panel nie ma linku i mówi, kiedy powstanie", async () => {
    renderOpen(
      <ClientPanelSlideOver
        open
        onOpenChange={vi.fn()}
        jobId={7}
        transport={transport({}, { ...QUIET, enabled: false, url: null, short_url: null })}
      />,
    );
    expect(await screen.findByText(/Link powstanie po włączeniu panelu/)).toBeInTheDocument();
    expect(screen.queryByTestId("client-panel-url")).toBeNull();
    expect(screen.queryByRole("button", { name: "Odwołaj link" })).toBeNull();
  });

  it("włączenie idzie od razu, wyłączenie dopiero po potwierdzeniu", async () => {
    const updateSettings = vi.fn().mockResolvedValue(undefined);
    renderOpen(
      <ClientPanelSlideOver
        open
        onOpenChange={vi.fn()}
        jobId={7}
        transport={transport({ updateSettings })}
      />,
    );
    await userEvent.click(await screen.findByRole("switch", { name: "Panel włączony" }));
    expect(await screen.findByText("Wyłączyć panel klienta?")).toBeInTheDocument();
    expect(updateSettings).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Wyłącz panel" }));
    await waitFor(() => expect(updateSettings).toHaveBeenCalledWith(7, { enabled: false }));

    await userEvent.click(screen.getByRole("switch", { name: "Stawka do klienta" }));
    await waitFor(() => expect(updateSettings).toHaveBeenCalledWith(7, { show_rate: false }));
  });

  it("„Odwołaj link” bez potwierdzenia niczego nie zmienia", async () => {
    const rotateLink = vi.fn().mockResolvedValue(undefined);
    renderOpen(
      <ClientPanelSlideOver open onOpenChange={vi.fn()} jobId={7} transport={transport({ rotateLink })} />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Odwołaj link" }));
    expect(await screen.findByText("Odwołać link?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Anuluj" }));
    expect(rotateLink).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Odwołaj link" }));
    const dialog = await confirmDialog();
    await userEvent.click(within(dialog).getByRole("button", { name: "Odwołaj link" }));
    await waitFor(() => expect(rotateLink).toHaveBeenCalledWith(7));
  });

  it("„Nieprawda” dokłada klucz do listy odrzuconych; ukrycie osoby to osobna zmiana", async () => {
    const updatePerson = vi.fn().mockResolvedValue(undefined);
    renderOpen(
      <ClientPanelSlideOver open onOpenChange={vi.fn()} jobId={7} transport={transport({ updatePerson })} />,
    );
    const anna = await screen.findByTestId("client-panel-person-1");
    await userEvent.click(within(anna).getAllByRole("button", { name: "Nieprawda" })[1]);
    const dialog = await confirmDialog();
    await userEvent.click(within(dialog).getByRole("button", { name: "Usuń dowód" }));
    await waitFor(() =>
      expect(updatePerson).toHaveBeenCalledWith(7, 1, { rejected_evidence: ["linux"] }),
    );

    await userEvent.click(within(anna).getByRole("button", { name: "Ukryj w panelu" }));
    await waitFor(() => expect(updatePerson).toHaveBeenCalledWith(7, 1, { hidden: true }));
  });

  it("otwarte sprawy otwierają „Od klienta”; adres spoza domen jest oznaczony", async () => {
    renderOpen(
      <ClientPanelSlideOver
        open
        onOpenChange={vi.fn()}
        jobId={7}
        transport={transport({}, { requests_open: 3 })}
      />,
    );
    expect(await screen.findByRole("tab", { name: "Od klienta (3)" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await userEvent.click(await screen.findByRole("button", { name: /Jan Testowy/ }));
    expect(screen.getByText("Adres spoza domen kontaktów klienta")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Otwórz osobę na Tablicy" })).toHaveAttribute(
      "href",
      "/jobs/7?candidate=2",
    );
  });

  it("mail na adres spoza domen wymaga potwierdzenia; bez maila idzie od razu", async () => {
    const answerRequest = vi.fn().mockResolvedValue(undefined);
    renderOpen(
      <ClientPanelSlideOver
        open
        onOpenChange={vi.fn()}
        jobId={7}
        transport={transport({ answerRequest }, { requests_open: 3 })}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /Jan Testowy/ }));
    await userEvent.type(screen.getByLabelText("Odpowiedź dla klienta"), "Tak, w projekcie.");
    await userEvent.click(screen.getByRole("checkbox", { name: /Wyślij też mailem/ }));
    await userEvent.click(screen.getByRole("button", { name: "Wyślij odpowiedź" }));
    expect(await screen.findByText("Wysłać mail na adres spoza domen klienta?")).toBeInTheDocument();
    expect(answerRequest).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Anuluj" }));

    await userEvent.click(screen.getByRole("checkbox", { name: /Wyślij też mailem/ }));
    await userEvent.click(screen.getByRole("button", { name: "Wyślij odpowiedź" }));
    await waitFor(() =>
      expect(answerRequest).toHaveBeenCalledWith(2, {
        answer: "Tak, w projekcie.",
        send_email: false,
      }),
    );
  });

  it("awaria listy spraw to komunikat z „Ponów”, nie „Klient nie czeka”", async () => {
    renderOpen(
      <ClientPanelSlideOver
        open
        onOpenChange={vi.fn()}
        jobId={7}
        transport={transport(
          { fetchRequests: () => Promise.reject(new Error("sieć")) },
          { requests_open: 1 },
        )}
      />,
    );
    expect(await screen.findByRole("button", { name: "Ponów" })).toBeInTheDocument();
    expect(screen.queryByText(/nie czeka/)).toBeNull();
  });

  it("odmowa dostępu z serwera wraca jako komunikat, nie pusty panel", async () => {
    renderOpen(
      <ClientPanelSlideOver
        open
        onOpenChange={vi.fn()}
        jobId={7}
        transport={transport({
          fetchSettings: () =>
            Promise.reject({
              isAxiosError: true,
              response: { status: 403, data: { detail: "Brak uprawnień do tej rekrutacji." } },
            }),
        })}
      />,
    );
    expect(await screen.findByText("Brak uprawnień do tej rekrutacji.")).toBeInTheDocument();
    expect(screen.queryByRole("switch")).toBeNull();
  });
});
