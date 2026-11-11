/**
 * „Dzwonienie”: kolejność listy, wynik jednym kliknięciem, daty powrotu, umówione
 * spotkanie, uprawnienia i ekran importu z losem każdego wiersza. Dane fikcyjne.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CallCard as CallCardData,
  CallQueue,
  ImportPreview,
  QueueItem,
} from "@/lib/api/sales-calling";

const queue = vi.fn();
const card = vi.fn();
const saveOutcome = vi.fn();
const createActivity = vi.fn();
const campaigns = vi.fn();
const preview = vi.fn();
const importList = vi.fn();
const briefing = vi.fn();
const askConfirm = vi.fn();
const showError = vi.fn();
const showSuccess = vi.fn();
let canEdit = true;
let previewData: ImportPreview | undefined;

const mutation = (mutate: ReturnType<typeof vi.fn>) => ({
  mutate,
  mutateAsync: mutate,
  isPending: false,
  reset: vi.fn(),
});

vi.mock("@/lib/api/sales-calling", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-calling")>()),
  useCallQueue: (campaignId: number | null) => queue(campaignId),
  useCallCard: () => card(),
  useSaveOutcome: () => mutation(saveOutcome),
  useCallCampaigns: () => campaigns(),
  useSaveCampaign: () => mutation(vi.fn()),
  usePreviewImport: () => ({ ...mutation(preview), data: previewData }),
  useImportList: () => mutation(importList),
}));
vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useCreateActivity: () => mutation(createActivity),
  useCompanyBriefing: () => briefing(),
  useOwnerCandidates: () => ({ data: [{ id: 9, name: "Druga Osoba" }] }),
  usePipelines: () => ({
    data: [{ id: 1, key: "sales", name: "Sprzedaż", is_default: true, stages: [{ id: 12, key: "qualifying-meeting" }] }],
  }),
}));
vi.mock("../OpportunityFormDialog", () => ({
  OpportunityFormDialog: ({
    defaults,
    onCreated,
  }: {
    defaults: Record<string, unknown>;
    onCreated: (opportunity: { id: number }) => void;
  }) => (
    <button type="button" data-defaults={JSON.stringify(defaults)} onClick={() => onCreated({ id: 77 })}>
      Formularz szansy
    </button>
  ),
}));
vi.mock("../SalesSelect", () => ({
  // Radix Select nie daje się wybrać w jsdom: w teście wystarcza zwykła lista.
  SalesSelect: ({
    id,
    value,
    onValueChange,
    options,
    anyLabel,
  }: {
    id?: string;
    value: string;
    onValueChange: (value: string) => void;
    options: { value: string; label: string }[];
    anyLabel?: string;
  }) => (
    <select id={id} value={value} onChange={(event) => onValueChange(event.target.value)}>
      {anyLabel !== undefined && <option value="">{anyLabel}</option>}
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError, showSuccess }) }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm, confirmDialog: null }),
}));
vi.mock("@/lib/permissions", async (original) => ({
  ...(await original<typeof import("@/lib/permissions")>()),
  hasPermission: () => canEdit,
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: object }) => unknown) => selector({ user: { id: 5, name: "Ja" } }),
}));

import { activeSection } from "../SalesShell";
import { CallingActions, CallQueueView } from "../calling/CallQueueView";
import { ImportListDialog } from "../calling/ImportListDialog";
import {
  fileProblem,
  importSummary,
  itemReason,
  nextKey,
  plusDaysIso,
  queueLine,
  resolveSelection,
} from "../calling/calling";

function item(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    key: "r:1",
    section: "new",
    record_id: 1,
    opportunity_id: null,
    opportunity_title: null,
    company: { id: 7, name: "Firma Testowa" },
    campaign: { id: 3, name: "Kampania Testowa" },
    person_name: "Jan Testowy",
    person_title: "Dyrektor IT",
    phone: "+48 600 100 200",
    state: "new",
    due_on: null,
    attempts: 0,
    last_outcome_at: null,
    since: "2026-11-06T10:00:00Z",
    ...overrides,
  };
}

function callQueue(overrides: Partial<CallQueue> = {}): CallQueue {
  const base: CallQueue = {
    today: "2026-11-10",
    counts: { callbacks: 0, meetings: 0, new: 0, later: 0 },
    callbacks: [],
    meetings: [],
    new: [],
    campaigns: [],
    ...overrides,
  };
  return {
    ...base,
    counts: {
      callbacks: base.callbacks.length,
      meetings: base.meetings.length,
      new: base.new.length,
      later: 0,
      ...overrides.counts,
    },
  };
}

function cardData(overrides: Partial<CallCardData> = {}): CallCardData {
  return {
    company: { id: 7, name: "Firma Testowa" },
    domain: null,
    contact_id: 31,
    email: "jan@firma-testowa.example",
    contact_source: "Lista z konferencji",
    note: null,
    service: "Usługa",
    script: "Otwarcie: jedno zdanie o usłudze.",
    do_not_contact: false,
    client_refusal: null,
    can_save: true,
    history: [
      { kind: "call", direction: "out", outcome: "offer_sent", subject: "Oferta ogólna wysłana: Jan Testowy", at: "2026-11-06T10:00:00Z" },
    ],
    ...overrides,
  };
}

const ok = <T,>(data: T) => ({ data, isLoading: false, error: null, isSuccess: true, refetch: vi.fn() });

const callback = item({
  key: "o:21",
  section: "callbacks",
  record_id: null,
  opportunity_id: 21,
  opportunity_title: "Oferta ogólna wysłana",
  campaign: null,
  company: { id: 8, name: "Oddzwonienie Sp. z o.o." },
});
const meeting = item({
  key: "o:22",
  section: "meetings",
  record_id: null,
  opportunity_id: 22,
  campaign: null,
  company: { id: 9, name: "Spotkanie S.A." },
});
const fresh = item();

beforeEach(() => {
  vi.clearAllMocks();
  canEdit = true;
  previewData = undefined;
  queue.mockReturnValue(ok(callQueue({ callbacks: [callback], meetings: [meeting], new: [fresh] })));
  card.mockReturnValue(ok(cardData()));
  campaigns.mockReturnValue(ok([{ id: 3, name: "Kampania Testowa", service: null, script: null, total: 0, counts: {} }]));
  saveOutcome.mockResolvedValue({ record_id: 1 });
  createActivity.mockResolvedValue({});
  briefing.mockReturnValue({ isSuccess: false });
});

describe("podpisy kolejki", () => {
  it("zakładka ma własny adres", () => {
    expect(activeSection("/sales/calling")).toBe("calling");
  });

  it("liczy dzień od daty z serwera i omija weekend", () => {
    expect(plusDaysIso("2026-11-10", 1)).toBe("2026-11-11");
    expect(plusDaysIso("2026-11-13", 1)).toBe("2026-11-16");
    expect(plusDaysIso("2026-11-10", 30)).toBe("2026-12-10");
  });

  it("opisuje powód pozycji i linię dnia", () => {
    expect(itemReason(meeting, "2026-11-10")).toBe("Spotkanie umówione, w NEXUSIE bez daty");
    expect(itemReason(callback, "2026-11-10")).toBe("Oferta ogólna wysłana · Lead od pt 06.11");
    expect(
      itemReason(
        item({ state: "offer_sent", attempts: 1, last_outcome_at: "2026-11-06T10:00:00Z", due_on: "2026-11-09" }),
        "2026-11-10",
      ),
    ).toBe("Oferta ogólna wysłana pt 06.11 · 2. rozmowa · termin minął pon 09.11");
    expect(queueLine(callQueue({ callbacks: [callback], counts: { callbacks: 1, meetings: 4, new: 148, later: 2 } }))).toBe(
      "1 do oddzwonienia · 4 spotkania bez terminu · 148 nowych w kolejce · 2 wróci w swoim dniu",
    );
  });

  it("po zapisie wskazuje następną pozycję, a z końca wraca na początek", () => {
    const items = [callback, meeting, fresh];
    expect(nextKey(items, "o:21")).toBe("o:22");
    expect(nextKey(items, "r:1")).toBe("o:21");
    expect(nextKey([fresh], "r:1")).toBeNull();
  });

  it("trzyma wybraną pozycję, a po jej zniknięciu bierze następną z poprzedniej kolejności", () => {
    const order = ["o:21", "o:22", "r:1"];
    // Nowa pozycja na górze listy nie podmienia wybranej.
    expect(resolveSelection([meeting, fresh], "r:1", order)?.key).toBe("r:1");
    // Zapisana zniknęła: następna po niej, nie pierwsza z góry.
    expect(resolveSelection([callback, fresh], "o:22", order)?.key).toBe("r:1");
    expect(resolveSelection([callback, meeting], "r:1", order)?.key).toBe("o:21");
    expect(resolveSelection([callback], null, [])?.key).toBe("o:21");
    expect(resolveSelection([], "r:1", order)).toBeNull();
  });

  it("odrzuca zły plik przed wysłaniem i streszcza podgląd", () => {
    expect(fileProblem({ name: "lista.pdf", size: 10 })).toMatch(/CSV albo Excel/);
    expect(fileProblem({ name: "lista.CSV", size: 3 * 1024 * 1024 })).toMatch(/2 MB/);
    expect(fileProblem({ name: "lista.xlsx", size: 10 })).toBeNull();
    expect(
      importSummary({
        addable: 5,
        without_company: 1,
        counts: { new_company: 3, linked: 2, already_in_campaign: 0, other_caller: 1, client: 2, do_not_contact: 0, no_phone: 4 },
      }),
    ).toBe(
      "5 trafi do kolejki, w tym 2 do istniejącej karty firmy · 1 dzwoni ktoś inny · 2 klienci NEXUSA · 4 bez telefonu · 1 bez nazwy firmy pominięto",
    );
  });
});

describe("kolejka", () => {
  it("trzyma stałą kolejność sekcji i zaczyna od pierwszej pozycji", () => {
    render(<CallQueueView />);
    const sections = screen.getAllByRole("region").map((section) => section.getAttribute("aria-label"));
    expect(sections.slice(0, 3)).toEqual([
      "Oddzwonienia na dziś",
      "Spotkania bez terminu · ustal datę",
      "Nowe rekordy kampanii",
    ]);
    const active = screen.getByRole("button", { current: true });
    expect(within(active).getByText("Oddzwonienie Sp. z o.o.")).toBeInTheDocument();
    expect(screen.getByText("1 z 3")).toBeInTheDocument();
    expect(screen.getByText("Otwarcie: jedno zdanie o usłudze.")).toBeInTheDocument();
    expect(screen.getByText(/Skąd kontakt: Lista z konferencji/)).toBeInTheDocument();
    expect(screen.getByText(/pt 06\.11 · Telefon · Oferta ogólna wysłana: Jan Testowy/)).toBeInTheDocument();
    expect(screen.getByText("Po zapisie od razu następna: Spotkanie S.A.")).toBeInTheDocument();
  });

  it("pokazuje punkty z researchu, gdy kanał jest włączony i firma je ma", () => {
    briefing.mockReturnValue({
      isSuccess: true,
      data: {
        enabled: true,
        briefing: {
          mode: "first_call",
          generated_at: "2026-11-09T08:00:00Z",
          points: [{ text: "Firma otwiera drugi magazyn", url: "https://example.com/magazyn", published: "2026-11-03" }],
        },
      },
    });
    render(<CallQueueView />);
    expect(screen.getByText(/Punkty do rozmowy na pierwszą rozmowę/)).toBeInTheDocument();
    expect(screen.getByText(/Firma otwiera drugi magazyn/)).toBeInTheDocument();
    // Skrypt kampanii i punkty stoją obok siebie w „Do rozmowy”.
    expect(screen.getByText("Otwarcie: jedno zdanie o usłudze.")).toBeInTheDocument();
  });

  it("awaria nie wygląda jak pusta kolejka, a pusta mówi, skąd wezmą się rekordy", () => {
    queue.mockReturnValue({ data: undefined, isLoading: false, error: { response: { status: 500 } }, isSuccess: false });
    const { unmount } = render(<CallQueueView />);
    expect(screen.getByText("Nie udało się pobrać danych")).toBeInTheDocument();
    expect(screen.queryByText("Kolejka jest pusta.")).not.toBeInTheDocument();
    unmount();
    queue.mockReturnValue(ok(callQueue()));
    render(<CallQueueView />);
    expect(screen.getByText("Kolejka jest pusta.")).toBeInTheDocument();
    expect(screen.getByText(/Zaimportuj listę do kampanii/)).toBeInTheDocument();
  });

  it("zapisuje wynik jednym kliknięciem i przechodzi do następnej pozycji", async () => {
    render(<CallQueueView />);
    fireEvent.change(screen.getByLabelText("Notatka z rozmowy"), { target: { value: " wróci po urlopie " } });
    fireEvent.click(screen.getByRole("button", { name: "Nie odebrał" }));
    expect(saveOutcome.mock.calls[0][0]).toEqual({ item: callback, outcome: "no_answer", note: "wróci po urlopie" });
    await waitFor(() => expect(showSuccess).toHaveBeenCalledWith("Zapisano: Nie odebrał."));
    expect(within(screen.getByRole("button", { current: true })).getByText("Spotkanie S.A.")).toBeInTheDocument();
  });

  it("odświeżenie kolejki nie podmienia karty, nad którą trwa praca", () => {
    queue.mockReturnValue(ok(callQueue({ new: [fresh] })));
    const view = render(<CallQueueView />);
    fireEvent.click(screen.getByRole("button", { name: "Umówione spotkanie" }));
    expect(screen.getByRole("button", { name: "Formularz szansy" })).toBeInTheDocument();
    // Założona szansa wskakuje do „spotkań bez terminu”, czyli nad wybrany rekord.
    queue.mockReturnValue(ok(callQueue({ meetings: [meeting], new: [fresh] })));
    view.rerender(<CallQueueView />);
    expect(within(screen.getByRole("button", { current: true })).getByText("Firma Testowa")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Formularz szansy" }));
    expect(saveOutcome.mock.calls[0][0]).toMatchObject({ item: fresh, outcome: "meeting_booked", opportunity_id: 77 });
  });

  it("„Oddzwonić” i „Nie teraz” pytają o dzień, reszta nie", () => {
    render(<CallQueueView />);
    fireEvent.click(screen.getByRole("button", { name: "Oddzwonić…" }));
    expect(saveOutcome).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Za 3 dni" }));
    expect(saveOutcome.mock.calls[0][0]).toMatchObject({ outcome: "call_back", callback_on: "2026-11-13" });

    fireEvent.click(screen.getByRole("button", { name: "Nie teraz…" }));
    fireEvent.change(screen.getByLabelText("Inna data"), { target: { value: "2027-01-15" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(saveOutcome.mock.calls[1][0]).toMatchObject({ outcome: "not_now", callback_on: "2027-01-15" });

    fireEvent.click(screen.getByRole("button", { name: "Oferta ogólna wysłana" }));
    expect(saveOutcome.mock.calls[2][0]).toMatchObject({ outcome: "offer_sent" });
    expect(saveOutcome.mock.calls[2][0].callback_on).toBeUndefined();
  });

  it("„Nie kontaktować” zapisuje dopiero po potwierdzeniu", async () => {
    askConfirm.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    render(<CallQueueView />);
    fireEvent.click(screen.getByRole("button", { name: "Nie kontaktować" }));
    await waitFor(() => expect(askConfirm).toHaveBeenCalledTimes(1));
    expect(saveOutcome).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Nie kontaktować" }));
    await waitFor(() => expect(saveOutcome).toHaveBeenCalled());
    expect(saveOutcome.mock.calls[0][0]).toMatchObject({ outcome: "do_not_contact" });
  });

  it("umówione spotkanie z rekordu kampanii zakłada szansę na etapie spotkania", () => {
    queue.mockReturnValue(ok(callQueue({ new: [fresh] })));
    render(<CallQueueView />);
    fireEvent.click(screen.getByRole("button", { name: "Umówione spotkanie" }));
    expect(saveOutcome).not.toHaveBeenCalled();
    const form = screen.getByRole("button", { name: "Formularz szansy" });
    expect(JSON.parse(form.getAttribute("data-defaults") ?? "{}")).toEqual({
      title: "Spotkanie wstępne",
      service_line: null,
      stage_id: 12,
      primary_contact_id: 31,
      source: "Dzwonienie",
      campaign: "Kampania Testowa",
    });
    fireEvent.click(form);
    expect(saveOutcome.mock.calls[0][0]).toMatchObject({ item: fresh, outcome: "meeting_booked", opportunity_id: 77 });
  });

  it("po nieudanym zapisie wyniku ponowienie nie zakłada drugiej szansy", async () => {
    queue.mockReturnValue(ok(callQueue({ new: [fresh] })));
    saveOutcome.mockRejectedValueOnce(new Error("sieć"));
    render(<CallQueueView />);
    fireEvent.click(screen.getByRole("button", { name: "Umówione spotkanie" }));
    fireEvent.click(screen.getByRole("button", { name: "Formularz szansy" }));
    await waitFor(() => expect(showError).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Umówione spotkanie" }));
    expect(saveOutcome).toHaveBeenCalledTimes(2);
    expect(saveOutcome.mock.calls[1][0]).toMatchObject({ outcome: "meeting_booked", opportunity_id: 77 });
  });

  it("umówione spotkanie przy szansie z etapu Lead nie otwiera formularza", () => {
    render(<CallQueueView />);
    fireEvent.click(screen.getByRole("button", { name: "Umówione spotkanie" }));
    expect(screen.queryByRole("button", { name: "Formularz szansy" })).not.toBeInTheDocument();
    expect(saveOutcome.mock.calls[0][0]).toEqual({ item: callback, outcome: "meeting_booked", note: undefined });
  });

  it("spotkanie bez terminu dostaje datę zamiast kolejnej szansy", async () => {
    render(<CallQueueView />);
    fireEvent.click(screen.getByText("Spotkanie S.A."));
    expect(screen.queryByRole("button", { name: "Umówione spotkanie" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Termin spotkania"), { target: { value: "2026-11-12T10:30" } });
    fireEvent.click(screen.getByRole("button", { name: /Zapisz termin/ }));
    expect(createActivity.mock.calls[0][0]).toEqual({
      kind: "meeting",
      opportunity_id: 22,
      subject: "Spotkanie kwalifikujące",
      occurred_at: new Date("2026-11-12T10:30").toISOString(),
    });
    await waitFor(() => expect(showSuccess).toHaveBeenCalledWith("Zapisano termin spotkania."));
  });

  it("klient NEXUSA: komunikat o Delivery Leadzie i zablokowane umawianie spotkania", () => {
    card.mockReturnValue(ok(cardData({ client_refusal: "Firma Testowa to klient NEXUSA, szansy nie zakładamy. Przekaż do: Opiekun Testowy." })));
    render(<CallQueueView />);
    expect(screen.getByRole("note")).toHaveTextContent("Przekaż do: Opiekun Testowy.");
    expect(screen.getByRole("button", { name: "Umówione spotkanie" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Nie odebrał" })).toBeEnabled();
  });

  it("sprzeciw zdejmuje numer, a cudza pozycja i sam podgląd nie zapisują wyniku", () => {
    card.mockReturnValue(ok(cardData({ do_not_contact: true, can_save: false })));
    const { unmount } = render(<CallQueueView />);
    expect(screen.queryByRole("link", { name: /Zadzwoń/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nie odebrał" })).toBeDisabled();
    expect(screen.getByText(/w kolejce innej osoby/)).toBeInTheDocument();
    unmount();

    canEdit = false;
    card.mockReturnValue(ok(cardData()));
    render(<CallQueueView />);
    expect(screen.getByRole("link", { name: /Zadzwoń \+48 600 100 200/ })).toHaveAttribute("href", "tel:+48600100200");
    expect(screen.getByRole("button", { name: "Nie odebrał" })).toBeDisabled();
  });

  it("kampanie i import w nagłówku widzi tylko osoba z prawem edycji", () => {
    const { unmount } = render(<CallingActions />);
    expect(screen.getByRole("button", { name: /Importuj listę/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Kampanie" }));
    expect(screen.getByText("Kampania Testowa")).toBeInTheDocument();
    unmount();
    canEdit = false;
    const hidden = render(<CallingActions />);
    expect(hidden.container).toBeEmptyDOMElement();
  });

  it("filtr kampanii pojawia się przy dwóch kampaniach i trafia do zapytania", () => {
    queue.mockReturnValue(
      ok(callQueue({ new: [fresh], campaigns: [{ id: 3, name: "Kampania Testowa" }, { id: 4, name: "Druga Kampania" }] })),
    );
    render(<CallQueueView />);
    fireEvent.click(screen.getByRole("button", { name: "Druga Kampania" }));
    expect(queue).toHaveBeenLastCalledWith(4);
  });
});

describe("import listy", () => {
  const file = new File(["firma;telefon\nA;600100200\n"], "lista.csv", { type: "text/csv" });
  const previewOf = (overrides: Partial<ImportPreview> = {}): ImportPreview => ({
    total: 3,
    addable: 1,
    to_decide: 2,
    without_company: 0,
    counts: { new_company: 1, linked: 0, already_in_campaign: 0, other_caller: 0, client: 1, do_not_contact: 0, no_phone: 1 },
    rows: [
      { line: 2, company: "Nowa Firma", person: "Adam Nowy", title: "CTO", phone: "600 400 001", fate: "new_company", detail: "Założy kartę firmy, dojdzie nowa osoba.", to_decide: false },
      { line: 3, company: "Klient Testowy", person: null, title: null, phone: "600 400 002", fate: "client", detail: "Klient Testowy to klient NEXUSA.", to_decide: true },
      { line: 4, company: "Bez Numeru", person: "Jan Bez", title: null, phone: null, fate: "no_phone", detail: "Brak numeru telefonu w wierszu.", to_decide: true },
    ],
    ...overrides,
  });

  it("odrzuca zły typ pliku i nie sprawdza listy bez kampanii", () => {
    render(<ImportListDialog open onOpenChange={vi.fn()} onNewCampaign={vi.fn()} />);
    const check = screen.getByRole("button", { name: "Sprawdź listę" });
    expect(check).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Plik z listą"), {
      target: { files: [new File(["x"], "lista.pdf", { type: "application/pdf" })] },
    });
    expect(showError).toHaveBeenCalledWith("Import przyjmuje plik CSV albo Excel (.xlsx).");
    expect(check).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Plik z listą"), { target: { files: [file] } });
    // Plik jest, kampanii nie wybrano.
    expect(check).toBeDisabled();
    expect(preview).not.toHaveBeenCalled();
  });

  it("pokazuje los każdego wiersza, filtr „do decyzji” i wymaga „Skąd kontakt”", () => {
    const onOpenChange = vi.fn();
    const view = render(<ImportListDialog open onOpenChange={onOpenChange} onNewCampaign={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Kampania"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Plik z listą"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Sprawdź listę" }));
    expect(preview.mock.calls[0][0]).toEqual({ campaign_id: 3, file, contact_source: "", assignee_user_id: 5 });

    previewData = previewOf();
    view.rerender(<ImportListDialog open onOpenChange={onOpenChange} onNewCampaign={vi.fn()} />);
    expect(screen.getByText("Lista do kampanii „Kampania Testowa”: 3 wierszy z pliku")).toBeInTheDocument();
    expect(screen.getByText("1 trafi do kolejki · 1 klienci NEXUSA · 1 bez telefonu")).toBeInTheDocument();
    for (const label of ["Nowa firma", "Klient NEXUSA", "Brak telefonu"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    const add = screen.getByRole("button", { name: "Dodaj 1 do kolejki" });
    expect(add).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Pokaż tylko do decyzji (2)" }));
    expect(screen.queryByText("Nowa Firma")).not.toBeInTheDocument();
    expect(screen.getByText("Klient Testowy")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Skąd kontakt/), { target: { value: "  Lista z targów " } });
    expect(add).toBeEnabled();
    importList.mockImplementation((_input, options) => options?.onSuccess?.({ added: 1 }));
    fireEvent.click(add);
    expect(importList.mock.calls[0][0]).toEqual({
      campaign_id: 3,
      file,
      contact_source: "Lista z targów",
      assignee_user_id: 5,
    });
    expect(showSuccess).toHaveBeenCalledWith("Dodano 1 do kolejki.");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
