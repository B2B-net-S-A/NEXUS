/**
 * Kartoteka → „Dane do rozliczeń” (etap 4, M7, R6). Widzą osoba, Kadry
 * i Płace; przełożony nie pyta serwera, a 404 chowa sekcję. Osoba widzi
 * swoje dane bez formularza. Formularz wysyła tylko zmienione pola, rachunek
 * jest zawsze 4 cyframi. Dane fikcyjne (fixtures harnessu).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: mocks.post, put: mocks.put } }));

import { olaBilling, settlementScene } from "@/app/preview/hr-settlements/fixtures";
import { ToastProvider } from "@/components/Toast";
import { settlementKeys } from "@/lib/api/hr-settlements";

import { BillingDetailsSection, billingChanges } from "../BillingDetailsSection";

function wrap(node: React.ReactNode, seed?: (client: QueryClient) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  seed?.(client);
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>{node}</ToastProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  mocks.put.mockReset();
});

const data = () => olaBilling(settlementScene());

describe("BillingDetailsSection", () => {
  it("przełożony (bez dostępu) nie pyta serwera i nie widzi sekcji", () => {
    wrap(<BillingDetailsSection userId={101} enabled={false} />);
    expect(mocks.get).not.toHaveBeenCalled();
    expect(screen.queryByText("Dane do rozliczeń")).toBeNull();
  });

  it("404 z serwera chowa sekcję", async () => {
    mocks.get.mockRejectedValue(Object.assign(new Error("x"), { response: { status: 404 } }));
    wrap(<BillingDetailsSection userId={101} enabled />);
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText("Wczytywanie…")).toBeNull());
    expect(screen.queryByText("Dane do rozliczeń")).toBeNull();
  });

  it("osoba widzi swoje dane bez formularza", () => {
    wrap(<BillingDetailsSection userId={101} enabled />, (client) =>
      client.setQueryData(settlementKeys.billing(101), { ...data(), can_edit: false }),
    );
    expect(screen.getByText("Dane do rozliczeń")).toBeInTheDocument();
    expect(screen.getByText("•• 4521 · z białej listy VAT")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zapisz" })).toBeNull();
    expect(screen.getByText(/zgłoś Kadrom/)).toBeInTheDocument();
  });

  it("Kadry zapisują tylko zmienione pola", async () => {
    const user = userEvent.setup();
    mocks.put.mockResolvedValue({ data: data() });
    wrap(<BillingDetailsSection userId={101} enabled />, (client) =>
      client.setQueryData(settlementKeys.billing(101), data()),
    );
    const terms = screen.getByLabelText("Termin płatności (dni)");
    await user.clear(terms);
    await user.type(terms, "21");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(mocks.put).toHaveBeenCalledWith("/api/hr/settlements/billing/101", {
      payment_terms_days: 21,
    });
  });

  it("zły NIP podpowiada już w formularzu", async () => {
    const user = userEvent.setup();
    wrap(<BillingDetailsSection userId={101} enabled />, (client) =>
      client.setQueryData(settlementKeys.billing(101), data()),
    );
    const nip = screen.getByLabelText("NIP");
    await user.clear(nip);
    await user.type(nip, "1234567890");
    expect(screen.getByText(/NIP ma 10 cyfr i sumę kontrolną/)).toBeInTheDocument();
  });
});

describe("billingChanges", () => {
  it("pusty NIP = usunięcie, puste pole rachunku = bez zmiany rachunku", () => {
    const current = { nip: "1234563218", payment_terms_days: 14, symfonia_id: "000127" };
    expect(billingChanges(current, { nip: "123-456-32-18", terms: "14", symfonia: "000127", account: "" })).toEqual({});
    expect(billingChanges(current, { nip: "", terms: "14", symfonia: "", account: "" })).toEqual({
      nip: null,
      symfonia_id: null,
    });
    expect(
      billingChanges(current, { nip: "1234563218", terms: "14", symfonia: "000127", account: " PL00 1111 " }),
    ).toEqual({ account: "PL00 1111" });
  });
});
