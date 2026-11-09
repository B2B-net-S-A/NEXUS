import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ConsultantPanelLayout from "@/app/konsultant/(panel)/layout";
import { PortalApiError, portalApi, savePortalSession, type PortalMe } from "@/lib/api/consultant-portal";

import { DocumentsSection } from "../DocumentsSection";
import { LoginForm } from "../LoginForm";
import { panelNavItems } from "../PanelNav";
import { EquipmentScreen, HelpScreen, SettlementScreen, StartScreen, TrainerScreen } from "../PanelScreens";

const ME: PortalMe = {
  first_name: "Anna",
  client: "Bank Przykładowy",
  since: "2024-01-15",
  until: null,
  support_email: "wsparcie@example.com",
  topics: [{ key: "invoice", label: "Faktury i płatności" }],
  rate: { amount: "160.00", currency: "PLN", unit: "hourly" },
  support_phone: null,
  menu: { start: true, equipment: false },
};

const Page = () => (
  <ConsultantPanelLayout>
    <p>Treść ekranu</p>
  </ConsultantPanelLayout>
);

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

function refuse(status: number, detail?: unknown) {
  return new PortalApiError(status, detail === undefined ? undefined : { detail });
}

describe("strefa konsultanta", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    vi.spyOn(portalApi, "faq").mockResolvedValue({ items: [] });
    vi.spyOn(portalApi, "cases").mockResolvedValue({ items: [] });
    vi.spyOn(portalApi, "meetings").mockResolvedValue({ items: [], note: "Rozmowa jest spisywana." });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("wyłączony portal mówi to zdaniem i nie pokazuje logowania", async () => {
    vi.spyOn(portalApi, "status").mockRejectedValue(refuse(404, "Not Found"));
    wrap(<Page />);
    expect(await screen.findByText("Panel konsultanta nie jest jeszcze dostępny")).toBeTruthy();
    expect(screen.queryByLabelText("Adres e-mail")).toBeNull();
  });

  it("awaria sieci nie wygląda jak wyłączony portal", { timeout: 12_000 }, async () => {
    vi.spyOn(portalApi, "status").mockRejectedValue(new TypeError("Failed to fetch"));
    wrap(<Page />);
    // Awaria sieci ma dwa ponowienia, zanim ekran o niej powie.
    expect(await screen.findByText("Nie udało się otworzyć panelu konsultanta", {}, { timeout: 8000 })).toBeTruthy();
    expect(screen.queryByText("Panel konsultanta nie jest jeszcze dostępny")).toBeNull();
  });

  it("bez sesji prosi o link", async () => {
    vi.spyOn(portalApi, "status").mockResolvedValue({ open: true });
    wrap(<Page />);
    expect(await screen.findByLabelText("Adres e-mail")).toBeTruthy();
  });

  it("wygasła sesja wraca do prośby o link i czyści token", async () => {
    savePortalSession("stary-token");
    vi.spyOn(portalApi, "status").mockResolvedValue({ open: true });
    vi.spyOn(portalApi, "me").mockRejectedValue(refuse(401, "Sesja wygasła."));
    wrap(<Page />);
    expect(await screen.findByText("Sesja wygasła")).toBeTruthy();
    expect(screen.getByLabelText("Adres e-mail")).toBeTruthy();
    await waitFor(() => expect(window.sessionStorage.length).toBe(0));
  });

  it("z sesją pokazuje menu i ekran", async () => {
    savePortalSession("token");
    vi.spyOn(portalApi, "status").mockResolvedValue({ open: true });
    vi.spyOn(portalApi, "me").mockResolvedValue(ME);
    wrap(<Page />);
    expect(await screen.findByText("Treść ekranu")).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "Panel konsultanta" })).toBeTruthy();
  });

  it("awaria spraw nie wygląda jak pusta lista", { timeout: 12_000 }, async () => {
    vi.spyOn(portalApi, "cases").mockRejectedValue(refuse(500));
    wrap(<HelpScreen me={ME} />);
    expect(await screen.findByText("Nie udało się wczytać spraw. Odśwież stronę.", {}, { timeout: 8000 })).toBeTruthy();
    expect(screen.queryByText("Nie masz otwartych spraw.")).toBeNull();
  });

  it("po prośbie o link pokazuje zdanie z serwera", async () => {
    vi.spyOn(portalApi, "requestLink").mockResolvedValue({ message: "Jeśli ten adres jest w umowach…" });
    wrap(<LoginForm />);
    await userEvent.type(screen.getByLabelText("Adres e-mail"), "anna@example.com");
    await userEvent.click(screen.getByRole("button", { name: /Wyślij link/ }));
    expect(await screen.findByText("Jeśli ten adres jest w umowach…")).toBeTruthy();
  });
});

describe("ekrany panelu", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("menu pokazuje Sprzęt i Na start tylko z treścią", () => {
    const labels = (menu: PortalMe["menu"]) => panelNavItems({ menu }).map((item) => item.label);
    expect(labels({ start: false, equipment: false })).not.toContain("Sprzęt");
    expect(labels({ start: false, equipment: false })).not.toContain("Na start");
    expect(labels({ start: true, equipment: true })).toEqual(expect.arrayContaining(["Sprzęt", "Na start"]));
  });

  it("Start pokazuje stawkę i pustą listę dopiero po wczytaniu", async () => {
    vi.spyOn(portalApi, "todo").mockResolvedValue({ items: [] });
    vi.spyOn(portalApi, "meetings").mockResolvedValue({ items: [], note: "" });
    wrap(<StartScreen me={ME} />);
    expect(screen.getByText("160,00 zł/h netto")).toBeTruthy();
    expect(await screen.findByText("Nic na Ciebie nie czeka.")).toBeTruthy();
  });

  it("awaria listy Do zrobienia nie mówi, że nic nie czeka", { timeout: 12_000 }, async () => {
    vi.spyOn(portalApi, "todo").mockRejectedValue(refuse(500));
    vi.spyOn(portalApi, "meetings").mockResolvedValue({ items: [], note: "" });
    wrap(<StartScreen me={ME} />);
    expect(await screen.findByRole("alert", {}, { timeout: 8000 })).toBeTruthy();
    expect(screen.queryByText("Nic na Ciebie nie czeka.")).toBeNull();
  });

  it("bez szablonu nie zgaduje sposobu rozliczenia", async () => {
    vi.spyOn(portalApi, "settlement").mockResolvedValue({
      mode: null,
      instructions: null,
      buyer: { name: "B2B.net S.A.", nip: "0000000000", address: "Ulica 1" },
      payment_days: 14,
    });
    wrap(<SettlementScreen me={ME} />);
    expect(await screen.findByText(/ustalają jeszcze Finanse/)).toBeTruthy();
    expect(screen.queryByText("Raport od klienta")).toBeNull();
  });

  it("szablon klienta pokazuje kroki i dopisek Finansów", async () => {
    vi.spyOn(portalApi, "settlement").mockResolvedValue({
      mode: "client_report",
      instructions: "Fakturę wystaw do 10.",
      buyer: { name: "B2B.net S.A.", nip: "0000000000", address: "Ulica 1" },
      payment_days: 14,
    });
    wrap(<SettlementScreen me={ME} />);
    expect(await screen.findByText("Raport od klienta")).toBeTruthy();
    expect(screen.getByText("Fakturę wystaw do 10.")).toBeTruthy();
  });

  it("potwierdzenie odbioru wysyła podpis i wraca do listy", async () => {
    vi.spyOn(portalApi, "equipment").mockResolvedValue({
      items: [],
      protocols: [
        {
          id: 7,
          number: "PZO/2026/11/1",
          kind: "wydanie",
          date: "2026-11-03",
          status: "oczekuje",
          label: "Czeka na Twoje potwierdzenie",
          items: ["Laptop"],
          can_confirm: true,
        },
      ],
    });
    const confirm = vi.spyOn(portalApi, "confirmProtocol").mockResolvedValue({ status: "podpisany" });
    wrap(<EquipmentScreen me={ME} />);
    await userEvent.click(await screen.findByRole("button", { name: "Potwierdź odbiór" }));
    await userEvent.type(screen.getByLabelText("Imię i nazwisko"), "Anna Przykładowa");
    await userEvent.click(screen.getByRole("button", { name: "Potwierdzam odbiór" }));
    await waitFor(() => expect(confirm).toHaveBeenCalledWith(7, "Anna Przykładowa"));
  });

  it("formularz trenera wymaga tematu i doświadczenia", async () => {
    vi.spyOn(portalApi, "trainer").mockResolvedValue({ application: null });
    const save = vi.spyOn(portalApi, "saveTrainer");
    wrap(<TrainerScreen />);
    const send = await screen.findByRole("button", { name: /Wyślij zgłoszenie/ });
    expect((send as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "AWS" }));
    expect((send as HTMLButtonElement).disabled).toBe(true);
    await userEvent.type(screen.getByLabelText("Doświadczenie trenerskie"), "Pięć lat szkoleń");
    expect((send as HTMLButtonElement).disabled).toBe(false);
    expect(save).not.toHaveBeenCalled();
  });
});

describe("dokumenty w panelu", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("pokazuje krok miesiąca bez kodu SMS", async () => {
    vi.spyOn(portalApi, "financeOverview").mockResolvedValue({
      months: [
        {
          year: 2026,
          month: 10,
          report_label: "Raport: zaakceptowany",
          invoice_label: "Faktura: wystaw i wyślij",
          issue_invoice: true,
          action: "send_invoice",
          documents: [],
        },
      ],
    });
    wrap(<DocumentsSection />);
    expect(await screen.findByRole("button", { name: /Wyślij fakturę/ })).toBeTruthy();
    expect(screen.getByText(/Faktura: wystaw i wyślij/)).toBeTruthy();
    expect(screen.queryByText(/kod/i)).toBeNull();
  });

  it("awaria nie wygląda jak pusta lista", { timeout: 12_000 }, async () => {
    vi.spyOn(portalApi, "financeOverview").mockRejectedValue(refuse(500));
    wrap(<DocumentsSection />);
    expect(await screen.findByRole("alert", {}, { timeout: 8000 })).toBeTruthy();
  });
});
