/**
 * Kartoteka → „Umowy” (E5). Sekcja chowa się przy 403/404 (przełożony, sama
 * osoba, wyłączony moduł) i gdy jest wyłączona; awaria to blok błędu, nie
 * pusta lista. Płace widzą umowy bez akcji. Wysyłka do podpisu dopiero po
 * potwierdzeniu, nieudane przepisanie do kartoteki widać przy umowie.
 * Okno szkicu zatrzymuje stawkę zlecenia poniżej minimum przed serwerem.
 * Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  put: vi.fn(),
}));
vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, post: mocks.post, patch: mocks.patch, put: mocks.put },
}));

// Lista wyboru i menu Radix w jsdom: brak API przechwytywania wskaźnika.
if (!Element.prototype.hasPointerCapture) {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => undefined,
    releasePointerCapture: () => undefined,
  });
}
if (!Element.prototype.scrollIntoView) {
  Object.assign(Element.prototype, { scrollIntoView: () => undefined });
}

import {
  ACTIVE_TEMPLATES,
  CELINA,
  OLA,
  PEOPLE,
  celinaAgreements,
  olaAgreements,
} from "@/app/preview/hr-agreements/fixtures";
import { ToastProvider } from "@/components/Toast";
import { hrKeys } from "@/lib/api/hr";
import { agreementKeys, type PersonAgreements } from "@/lib/api/hr-agreements";

import { AgreementDialog } from "../AgreementDialog";
import { PersonAgreementsSection } from "../PersonAgreementsSection";

vi.setConfig({ testTimeout: 20_000 });

function wrap(node: React.ReactNode, userId: number, data?: PersonAgreements) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  if (data) client.setQueryData(agreementKeys.person(userId), data);
  client.setQueryData(agreementKeys.templates(true), ACTIVE_TEMPLATES);
  client.setQueryData(hrKeys.people, PEOPLE);
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>{node}</ToastProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
});

describe("PersonAgreementsSection", () => {
  it("wyłączona sekcja nie pyta serwera", () => {
    wrap(<PersonAgreementsSection userId={CELINA.id} enabled={false} />, CELINA.id);
    expect(mocks.get).not.toHaveBeenCalled();
    expect(screen.queryByText("Umowy")).toBeNull();
  });

  it("403 z serwera (przełożony, sama osoba) chowa sekcję", async () => {
    mocks.get.mockRejectedValue(Object.assign(new Error("x"), { response: { status: 403 } }));
    wrap(<PersonAgreementsSection userId={CELINA.id} enabled />, CELINA.id);
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText("Wczytywanie…")).toBeNull());
    expect(screen.queryByText("Umowy")).toBeNull();
  });

  it("awaria serwera to błąd z ponowieniem, nie pusta lista", async () => {
    mocks.get.mockRejectedValue(Object.assign(new Error("x"), { response: { status: 500 } }));
    wrap(<PersonAgreementsSection userId={CELINA.id} enabled />, CELINA.id);
    expect(await screen.findByText("Nie udało się wczytać umów.")).toBeTruthy();
    expect(screen.queryByText("Nie ma jeszcze umów przygotowanych w NEXUSIE.")).toBeNull();
  });

  it("Kadry: umowy z kanałem podpisu i akcją wiersza", () => {
    wrap(<PersonAgreementsSection userId={CELINA.id} enabled />, CELINA.id, celinaAgreements());
    expect(screen.getByRole("button", { name: /Nowa umowa albo aneks/ })).toBeTruthy();
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByText("wysłana do podpisu")).toBeTruthy();
    expect(within(rows[0]).getByRole("button", { name: "Wycofaj z podpisu" })).toBeTruthy();
    expect(within(rows[1]).getByText(/ręcznie, ze skanem/)).toBeTruthy();
    expect(within(rows[2]).getByText("31,40 zł brutto za godzinę")).toBeTruthy();
  });

  it("Płace: te same umowy bez akcji zmieniających", () => {
    wrap(<PersonAgreementsSection userId={CELINA.id} enabled />, CELINA.id, celinaAgreements(false));
    expect(screen.queryByRole("button", { name: /Nowa umowa albo aneks/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Wycofaj z podpisu" })).toBeNull();
    expect(screen.getAllByRole("row")).toHaveLength(4);
  });

  it("wysyłka do podpisu dopiero po potwierdzeniu", async () => {
    const user = userEvent.setup();
    const data = olaAgreements();
    mocks.post.mockResolvedValue({ data: { ...data.agreements[0], status: "sent" } });
    wrap(<PersonAgreementsSection userId={OLA.id} enabled />, OLA.id, data);
    // Nieudana wcześniejsza wysyłka i nieprzepisana umowa widać przy wierszach.
    expect(screen.getByText(/Autenti nie przyjęło umowy/)).toBeTruthy();
    expect(screen.getByText(/nie przeszła do kartoteki/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Wyślij do podpisu" }));
    expect(mocks.post).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Wyślij do podpisu" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/api/hr/agreements/52/send"));
  });
});

describe("AgreementDialog", () => {
  it("zatrzymuje stawkę zlecenia poniżej minimum i brak wzoru, zanim pójdzie zapis", async () => {
    const user = userEvent.setup();
    const overview = celinaAgreements();
    wrap(<AgreementDialog overview={overview} onClose={() => undefined} />, CELINA.id, overview);
    await user.click(screen.getByRole("button", { name: "Utwórz szkic" }));
    expect(await screen.findByText("Wybierz wzór umowy.")).toBeTruthy();
    await user.click(screen.getByRole("combobox", { name: /Wzór/ }));
    await user.click(await screen.findByRole("option", { name: /Zlecenie — recepcja · wersja 3/ }));
    const rate = screen.getByLabelText(/Stawka brutto za godzinę/);
    await user.clear(rate);
    await user.type(rate, "30,00");
    fireEvent.change(screen.getByLabelText(/^Od/), { target: { value: "2026-11-01" } });
    await user.click(screen.getByRole("button", { name: "Utwórz szkic" }));
    expect(await screen.findByText("Minimalna stawka na zleceniu w 2026 to 31,40 zł/h brutto.")).toBeTruthy();
    expect(mocks.post).not.toHaveBeenCalled();
    // Po podpisie: lista z makiety dla zlecenia.
    expect(screen.getByText("przekaże dane do Symfonii przy najbliższym eksporcie")).toBeTruthy();

    mocks.post.mockResolvedValue({ data: { ...overview.agreements[2], status: "draft", warning: null } });
    await user.clear(rate);
    await user.type(rate, "32,50");
    await user.click(screen.getByRole("button", { name: "Utwórz szkic" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    const [url, body] = mocks.post.mock.calls[0];
    expect(url).toBe(`/api/hr/agreements/people/${CELINA.id}`);
    expect(body).toMatchObject({
      template_id: 31,
      hourly_rate: "32.50",
      start_date: "2026-11-01",
      end_date: null,
      hours_confirmation: true,
      payout_day: 10,
      coordinator_user_id: 105,
    });
  });
});
