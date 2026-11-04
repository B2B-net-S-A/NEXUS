import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ConsultantPortalPage from "@/app/konsultant/page";
import { PortalApiError, portalApi, savePortalSession, type PortalMe } from "@/lib/api/consultant-portal";

import { FinanceSection } from "../FinanceSection";
import { LoginForm } from "../LoginForm";

const ME: PortalMe = {
  first_name: "Anna",
  client: "Bank Przykładowy",
  since: "2024-01-15",
  until: null,
  support_email: "wsparcie@example.com",
  topics: [{ key: "invoice", label: "Faktury i płatności" }],
};

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
    wrap(<ConsultantPortalPage />);
    expect(await screen.findByText("Strefa konsultanta nie jest jeszcze dostępna")).toBeTruthy();
    expect(screen.queryByLabelText("Adres e-mail")).toBeNull();
  });

  it("awaria sieci nie wygląda jak wyłączony portal", { timeout: 12_000 }, async () => {
    vi.spyOn(portalApi, "status").mockRejectedValue(new TypeError("Failed to fetch"));
    wrap(<ConsultantPortalPage />);
    // Awaria sieci ma dwa ponowienia, zanim ekran o niej powie.
    expect(await screen.findByText("Nie udało się otworzyć strefy konsultanta", {}, { timeout: 8000 })).toBeTruthy();
    expect(screen.queryByText("Strefa konsultanta nie jest jeszcze dostępna")).toBeNull();
  });

  it("bez sesji prosi o link", async () => {
    vi.spyOn(portalApi, "status").mockResolvedValue({ open: true });
    wrap(<ConsultantPortalPage />);
    expect(await screen.findByLabelText("Adres e-mail")).toBeTruthy();
  });

  it("wygasła sesja wraca do prośby o link i czyści token", async () => {
    savePortalSession("stary-token");
    vi.spyOn(portalApi, "status").mockResolvedValue({ open: true });
    vi.spyOn(portalApi, "me").mockRejectedValue(refuse(401, "Sesja wygasła."));
    wrap(<ConsultantPortalPage />);
    expect(await screen.findByText("Sesja wygasła")).toBeTruthy();
    expect(screen.getByLabelText("Adres e-mail")).toBeTruthy();
    await waitFor(() => expect(window.sessionStorage.length).toBe(0));
  });

  it("awaria spraw nie wygląda jak pusta lista", { timeout: 12_000 }, async () => {
    savePortalSession("token");
    vi.spyOn(portalApi, "status").mockResolvedValue({ open: true });
    vi.spyOn(portalApi, "me").mockResolvedValue(ME);
    vi.spyOn(portalApi, "cases").mockRejectedValue(refuse(500));
    vi.spyOn(portalApi, "financeStatus").mockResolvedValue({
      available: false,
      message: "Faktury i raporty są chwilowo niedostępne.",
      verified: false,
      phone_hint: null,
    });
    wrap(<ConsultantPortalPage />);
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

describe("finanse w strefie konsultanta", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("bez dostawcy SMS sekcja mówi, że jest niedostępna", async () => {
    vi.spyOn(portalApi, "financeStatus").mockResolvedValue({
      available: false,
      message: "Faktury i raporty są chwilowo niedostępne.",
      verified: false,
      phone_hint: null,
    });
    const overview = vi.spyOn(portalApi, "financeOverview");
    wrap(<FinanceSection supportEmail={null} />);
    expect(await screen.findByText("Faktury i raporty są chwilowo niedostępne.")).toBeTruthy();
    expect(overview).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Wyślij kod/ })).toBeNull();
  });

  it("przed kodem nie czyta dokumentów", async () => {
    vi.spyOn(portalApi, "financeStatus").mockResolvedValue({
      available: true,
      message: null,
      verified: false,
      phone_hint: "••• 123",
    });
    const overview = vi.spyOn(portalApi, "financeOverview");
    wrap(<FinanceSection supportEmail="wsparcie@example.com" />);
    expect(await screen.findByRole("button", { name: "Wyślij kod SMS" })).toBeTruthy();
    expect(overview).not.toHaveBeenCalled();
  });

  it("zły kod pokazuje komunikat serwera i czyści pole", async () => {
    vi.spyOn(portalApi, "financeStatus").mockResolvedValue({
      available: true,
      message: null,
      verified: false,
      phone_hint: "••• 123",
    });
    vi.spyOn(portalApi, "sendCode").mockResolvedValue({ phone_hint: "••• 123" });
    vi.spyOn(portalApi, "verifyCode").mockRejectedValue(
      refuse(422, { message: "Ten kod nie pasuje albo wygasł.", code: "bad_code" }),
    );
    wrap(<FinanceSection supportEmail={null} />);
    await userEvent.click(await screen.findByRole("button", { name: "Wyślij kod SMS" }));
    const input = await screen.findByLabelText("Kod SMS");
    await userEvent.type(input, "123456");
    await userEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(await screen.findByText("Ten kod nie pasuje albo wygasł.")).toBeTruthy();
    expect((input as HTMLInputElement).value).toBe("");
  });

  it("po kodzie pokazuje krok miesiąca", async () => {
    vi.spyOn(portalApi, "financeStatus").mockResolvedValue({
      available: true,
      message: null,
      verified: true,
      phone_hint: "••• 123",
    });
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
    wrap(<FinanceSection supportEmail={null} />);
    expect(await screen.findByRole("button", { name: /Wyślij fakturę/ })).toBeTruthy();
    expect(screen.getByText(/Faktura: wystaw i wyślij/)).toBeTruthy();
  });
});
