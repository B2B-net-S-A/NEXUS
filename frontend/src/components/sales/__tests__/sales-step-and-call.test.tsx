/**
 * Krok na tablicy i karcie, zapis rozmowy, sprzeciw wobec kontaktu i przeciąganie.
 */
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DecisionMapEntry, Opportunity, OpportunityDetail, Stage } from "@/lib/api/sales";

const logCall = vi.fn();
const createActivity = vi.fn();
const askConfirm = vi.fn();
const moveAsync = vi.fn();
const refetch = vi.fn();
const showError = vi.fn();
const showSuccess = vi.fn();
const showActionToast = vi.fn();

vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useLogCall: () => ({ mutate: logCall, isPending: false }),
  useCreateActivity: () => ({ mutate: createActivity, isPending: false }),
  useMoveOpportunity: () => ({ mutateAsync: moveAsync, isPending: false }),
  useSalesContacts: () => ({ data: { items: [] }, isSuccess: true }),
  useLinkOpportunityContact: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError, showSuccess, showActionToast }),
}));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm, confirmDialog: null }),
}));

import { CallLogPanel } from "../CallLogPanel";
import { NextStepDialog, type CallPerson } from "../CallLogDialogs";
import { OpportunityContacts } from "../OpportunityContacts";
import { OpportunityStepBar } from "../OpportunityStepBar";
import { SalesMotionPanel } from "../SalesMotionPanel";
import {
  amountLabel,
  boardCounters,
  callAdvice,
  callQueue,
  canDragOpportunity,
  canUndoMove,
  lastContactLabel,
  outcomePreset,
  shortCompany,
  stepLabel,
  stepTone,
} from "../step";
import { useBoardMove } from "../useBoardMove";

const stage = (id: number, outcome: Stage["outcome"], qualifies = false, position = id): Stage => ({
  id,
  key: `s${id}`,
  name: `Etap ${id}`,
  position,
  probability: 0,
  outcome,
  qualifies,
  color: null,
});

const opportunity = (over: Partial<Opportunity> = {}): Opportunity =>
  ({
    id: 1,
    title: "Zespół",
    status: "open",
    archived_at: null,
    stage: stage(1, "open"),
    company: { id: 3, name: "Firma" },
    value: null,
    mrr_value: null,
    one_off_value: null,
    currency: "PLN",
    owner: { id: 7, name: "Opiekun" },
    next_step: null,
    overdue_step: null,
    last_contact: null,
    waiting_for_reply: false,
    step_alarm: false,
    last_touch_at: "2026-11-01T10:00:00Z",
    ...over,
  }) as Opportunity;

const person = (over: Partial<DecisionMapEntry>): DecisionMapEntry => ({
  name: "Osoba",
  key: "k",
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe("krok na kafelku", () => {
  it("nazywa rodzaj i dzień", () => {
    expect(stepLabel(opportunity({ next_step: { kind: "call", at: "2026-11-30T09:00:00Z", subject: null } }))).toBe(
      "telefon 30.11",
    );
    expect(stepLabel(opportunity({ next_step: { kind: "task", at: "2026-11-12T09:00:00Z", subject: "X" } }))).toBe(
      "zadanie 12.11",
    );
    expect(stepLabel(opportunity({ next_step: { kind: "meeting", at: "2026-11-13T09:00:00Z", subject: "X" } }))).toBe(
      "spotkanie 13.11",
    );
  });

  it("zaległość pokazuje osobno, a brak kroku wprost", () => {
    const overdue = opportunity({ overdue_step: { kind: "task", at: "2026-08-07T09:00:00Z", subject: "X" } });
    expect(stepLabel(overdue)).toBe("zaległe 07.08");
    expect(stepTone(overdue)).toBe("warning");
    expect(stepLabel(opportunity())).toBe("brak kroku");
    expect(stepTone(opportunity())).toBe("neutral");
  });

  it("czerwień tylko przy alarmie z backendu", () => {
    expect(stepTone(opportunity({ step_alarm: true }))).toBe("danger");
  });

  it("krok ma pierwszeństwo przed zaległością", () => {
    const both = opportunity({
      next_step: { kind: "task", at: "2026-11-20T09:00:00Z", subject: "A" },
      overdue_step: { kind: "task", at: "2026-08-07T09:00:00Z", subject: "B" },
    });
    expect(stepLabel(both)).toBe("zadanie 20.11");
    expect(stepTone(both)).toBe("info");
  });
});

describe("ostatni kontakt na kafelku", () => {
  it("mówi, w którą stronę szedł mail", () => {
    const at = "2026-10-28T10:00:00Z";
    expect(lastContactLabel({ kind: "email", direction: "out", at })).toBe("28.10 mail od nas");
    expect(lastContactLabel({ kind: "email", direction: "in", at })).toBe("28.10 mail od klienta");
    expect(lastContactLabel({ kind: "email", direction: null, at })).toBe("28.10 mail");
    expect(lastContactLabel({ kind: "call", direction: null, at })).toBe("28.10 telefon");
    expect(lastContactLabel({ kind: "note", direction: null, at })).toBe("28.10 notatka");
    expect(lastContactLabel(null)).toBe("brak kontaktu");
  });
});

describe("kwota na kafelku", () => {
  it("miesięczna ma dopisek", () => {
    expect(amountLabel(opportunity({ value: "40000", mrr_value: "40000" }))).toMatch(/^40\s000 zł mies\.$/);
  });
  it("jednorazowa i łączna są nazwane", () => {
    expect(amountLabel(opportunity({ value: "9000", one_off_value: "9000" }))).toMatch(/jednorazowo$/);
    expect(amountLabel(opportunity({ value: "9000", mrr_value: "1000", one_off_value: "8000" }))).toMatch(/łącznie$/);
  });
  it("sama wartość z importu nie jest miesięczna", () => {
    expect(amountLabel(opportunity({ value: "9000" }))).toMatch(/^9\s?000 zł$/);
    expect(amountLabel(opportunity())).toBe("bez kwoty");
  });
});

describe("nazwa firmy na kafelku", () => {
  it("nie niesie formy prawnej", () => {
    expect(shortCompany("PRODUS Spółka z ograniczoną odpowiedzialnością")).toBe("PRODUS");
    expect(shortCompany("Frapol Sp. z o.o.")).toBe("Frapol");
    expect(shortCompany("Valeo S.A.")).toBe("Valeo");
  });
});

describe("liczniki nad tablicą", () => {
  it("liczą tylko otwarte", () => {
    const items = [
      opportunity(),
      opportunity({ waiting_for_reply: true }),
      opportunity({ next_step: { kind: "task", at: "2026-11-30T09:00:00Z", subject: "A" } }),
      opportunity({ overdue_step: { kind: "task", at: "2026-08-07T09:00:00Z", subject: "A" } }),
      opportunity({ status: "won" }),
    ];
    expect(boardCounters(items)).toEqual({ open: 4, noStep: 2, waiting: 1 });
  });
});

describe("kolejka telefonów", () => {
  it("najpierw decydujący, bez sprzeciwu i tylko z numerem", () => {
    const queue = callQueue([
      person({ name: "Wpływa", key: "a", our_role: "influencer", phone: "1" }),
      person({ name: "Champion", key: "b", our_role: "champion", phone: "2" }),
      person({ name: "Decydent", key: "c", our_role: "decision_maker", phone: "3" }),
      person({ name: "Sprzeciw", key: "d", our_role: "champion", phone: "4", do_not_contact: true }),
      person({ name: "Bez numeru", key: "e", our_role: "champion" }),
    ]);
    expect(queue.map((entry) => entry.name)).toEqual(["Champion", "Decydent"]);
  });

  it("poziom decyzji wskazuje, gdy nikt nie ma roli", () => {
    const queue = callQueue([
      person({ name: "Zespół", key: "a", decision_level: 4, phone: "1" }),
      person({ name: "Dyrektor", key: "b", decision_level: 2, phone: "2" }),
    ]);
    expect(queue.map((entry) => entry.name)).toEqual(["Dyrektor"]);
  });

  it("bez wskazań nie ma podpowiedzi", () => {
    expect(callQueue([person({ name: "Ktoś", phone: "1" })])).toEqual([]);
    expect(callAdvice([])).toBeNull();
  });

  it("nie odmienia nazwisk", () => {
    expect(callAdvice([person({ name: "A B" })])).toBe("Zadzwoń: A B");
    expect(callAdvice([person({ name: "A B" }), person({ name: "C D" })])).toBe("Zadzwoń: A B, potem C D");
  });
});

describe("co dalej po rozmowie", () => {
  it("podpowiada zadanie i termin", () => {
    expect(outcomePreset("no_answer")).toEqual({ what: "Zadzwonić ponownie", days: 1 });
    expect(outcomePreset("wants_offer")).toEqual({ what: "Przygotować i wysłać ofertę", days: 7 });
    expect(outcomePreset("not_now")).toEqual({ what: "Wrócić do tematu", days: 30 });
  });
});

describe("przeciąganie", () => {
  it("tylko otwarta szansa na etapie bez wyniku, tylko z prawem edycji", () => {
    expect(canDragOpportunity(opportunity(), true)).toBe(true);
    expect(canDragOpportunity(opportunity(), false)).toBe(false);
    expect(canDragOpportunity(opportunity({ status: "won", stage: stage(9, "won") }), true)).toBe(false);
    expect(canDragOpportunity(opportunity({ archived_at: "2026-01-01T00:00:00Z" }), true)).toBe(false);
  });

  it("nie proponuje cofnięcia, gdy ruch mógł ustawić kwalifikację", () => {
    const stages = [stage(1, "open"), stage(2, "open"), stage(3, "open", true), stage(4, "open")];
    expect(canUndoMove(stages[0], stages[1], stages)).toBe(true);
    expect(canUndoMove(stages[1], stages[2], stages)).toBe(false);
    expect(canUndoMove(stages[1], stages[3], stages)).toBe(false);
  });

  it("nie proponuje cofnięcia, gdy powrót wchodziłby na linię kwalifikacji", () => {
    const stages = [stage(1, "open"), stage(2, "open"), stage(3, "open", true), stage(4, "open")];
    expect(canUndoMove(stages[2], stages[0], stages)).toBe(false);
    expect(canUndoMove(stages[3], stages[1], stages)).toBe(false);
  });

  it("bez etapu kwalifikującego cofnięcie jest bezpieczne", () => {
    const stages = [stage(1, "open"), stage(2, "open")];
    expect(canUndoMove(stages[0], stages[1], stages)).toBe(true);
    expect(canUndoMove(stages[1], stages[0], stages)).toBe(true);
  });

  it("ruch z etapu kwalifikującego do tyłu nie dostaje „Cofnij”", async () => {
    moveAsync.mockResolvedValue({});
    const stages = [stage(1, "open"), stage(2, "open", true)];
    const { result } = renderHook(() => useBoardMove({ stages, refetch }));
    await act(async () => {
      await result.current.moveToStage(opportunity({ stage: stages[1], qualified_at: null } as Partial<Opportunity>), stages[0]);
    });
    expect(showActionToast).not.toHaveBeenCalled();
    expect(showSuccess).toHaveBeenCalledTimes(1);
  });

  it("po błędzie karta wraca, a komunikat mówi co się stało", async () => {
    moveAsync.mockRejectedValueOnce({ response: { data: { detail: "Ten etap nie należy do lejka." } } });
    const stages = [stage(1, "open"), stage(2, "open")];
    const { result } = renderHook(() => useBoardMove({ stages, refetch }));
    await act(async () => {
      await result.current.moveToStage(opportunity(), stages[1]);
    });
    expect(result.current.stageOf(opportunity())).toBe(1);
    expect(showError).toHaveBeenCalledWith("Ten etap nie należy do lejka.");
    expect(showActionToast).not.toHaveBeenCalled();
  });

  it("na czas zapisu karta stoi w nowej kolumnie", async () => {
    let finish: () => void = () => undefined;
    moveAsync.mockReturnValueOnce(new Promise<void>((resolve) => (finish = resolve)));
    const stages = [stage(1, "open"), stage(2, "open")];
    const { result } = renderHook(() => useBoardMove({ stages, refetch }));
    act(() => {
      void result.current.moveToStage(opportunity(), stages[1]);
    });
    expect(result.current.stageOf(opportunity())).toBe(2);
    await act(async () => {
      finish();
    });
    await waitFor(() => expect(refetch).toHaveBeenCalled());
  });

  it("proponuje „Cofnij” przed linią kwalifikacji", async () => {
    moveAsync.mockResolvedValue({});
    const stages = [stage(1, "open"), stage(2, "open"), stage(3, "open", true)];
    const { result } = renderHook(() => useBoardMove({ stages, refetch }));
    await act(async () => {
      await result.current.moveToStage(opportunity(), stages[1]);
    });
    expect(showActionToast).toHaveBeenCalledTimes(1);
    expect(showActionToast.mock.calls[0][1].actionLabel).toBe("Cofnij");
    await act(async () => {
      await showActionToast.mock.calls[0][1].onAction();
    });
    expect(moveAsync).toHaveBeenLastCalledWith({ id: 1, stage_id: 1 });
  });

  it("bez „Cofnij” na etapie kwalifikującym", async () => {
    moveAsync.mockResolvedValue({});
    const stages = [stage(1, "open"), stage(2, "open"), stage(3, "open", true)];
    const { result } = renderHook(() => useBoardMove({ stages, refetch }));
    await act(async () => {
      await result.current.moveToStage(opportunity(), stages[2]);
    });
    expect(showActionToast).not.toHaveBeenCalled();
    expect(showSuccess).toHaveBeenCalled();
  });

  it("upuszczenie na ten sam etap nic nie robi", async () => {
    const stages = [stage(1, "open"), stage(2, "open")];
    const { result } = renderHook(() => useBoardMove({ stages, refetch }));
    await act(async () => {
      await result.current.moveToStage(opportunity(), stages[0]);
    });
    expect(moveAsync).not.toHaveBeenCalled();
  });
});

const motion = (entries: DecisionMapEntry[]) =>
  ({ it_factory: { decision_map: entries }, meddic: null, products: [], subscription_items: [] }) as never;

describe("mapa decyzyjna na karcie", () => {
  it("numer osoby bez sprzeciwu jest klikalny i otwiera zapis", () => {
    const onCall = vi.fn();
    render(
      <SalesMotionPanel opportunityId={1} motion={motion([person({ name: "Anna", phone: "600 700 800" })])} onCall={onCall} />,
    );
    const link = screen.getByRole("link", { name: "600 700 800" });
    expect(link.getAttribute("href")).toBe("tel:600700800");
    fireEvent.click(link);
    expect(onCall).toHaveBeenCalledWith(expect.objectContaining({ name: "Anna" }));
  });

  it("numer osoby ze sprzeciwem przestaje być klikalny", () => {
    render(
      <SalesMotionPanel
        opportunityId={1}
        motion={motion([person({ name: "Anna", phone: "600 700 800", email: "a@b.pl", do_not_contact: true })])}
      />,
    );
    expect(screen.queryByRole("link", { name: "600 700 800" })).toBeNull();
    expect(screen.getByText("Nie kontaktować")).toBeTruthy();
    expect(screen.getByText("nie dzwonić")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Anna/ }));
    expect(screen.queryByRole("link", { name: "a@b.pl" })).toBeNull();
  });
});

describe("kontakty szansy", () => {
  const detail = (over: Partial<OpportunityDetail["contacts"][number]>) =>
    ({
      id: 1,
      company: { id: 3, name: "Firma" },
      contacts: [
        { id: 5, full_name: "Jan", title: null, email: "j@b.pl", phone: "500100200", role: null, do_not_contact_at: null, ...over },
      ],
    }) as unknown as OpportunityDetail;

  it("numer jest klikalny", () => {
    render(<OpportunityContacts opportunity={detail({})} canEdit={false} />);
    expect(screen.getByRole("link", { name: "500100200" }).getAttribute("href")).toBe("tel:500100200");
  });

  it("po sprzeciwie numer i mail są zwykłym tekstem", () => {
    render(<OpportunityContacts opportunity={detail({ do_not_contact_at: "2026-11-09T10:00:00Z" })} canEdit={false} />);
    expect(screen.queryByRole("link", { name: "500100200" })).toBeNull();
    expect(screen.queryByRole("link", { name: "j@b.pl" })).toBeNull();
    expect(screen.getByText("Nie kontaktować")).toBeTruthy();
  });
});

describe("pasek kroku", () => {
  const handlers = { onPlan: vi.fn(), onLog: vi.fn(), onOwner: vi.fn() };

  it("bez kroku podpowiada, do kogo dzwonić", () => {
    render(
      <OpportunityStepBar
        opportunity={opportunity() as OpportunityDetail}
        queue={[person({ name: "Anna Nowak" })]}
        canEdit
        canChangeOwner
        {...handlers}
      />,
    );
    expect(screen.getByText("Zadzwoń: Anna Nowak")).toBeTruthy();
    expect(screen.getByText("Brak kroku").className).not.toMatch(/danger|destructive/);
  });

  it("alarm z backendu to czerwień", () => {
    render(
      <OpportunityStepBar opportunity={opportunity({ step_alarm: true }) as OpportunityDetail} queue={[]} canEdit canChangeOwner {...handlers} />,
    );
    expect(screen.getByText("Brak kroku").className).toMatch(/danger|destructive/);
  });

  it("pokazuje ustalony krok z datą", () => {
    render(
      <OpportunityStepBar
        opportunity={opportunity({ next_step: { kind: "task", at: "2026-11-20T09:00:00Z", subject: "Wysłać ofertę" } }) as OpportunityDetail}
        queue={[]}
        canEdit
        canChangeOwner
        {...handlers}
      />,
    );
    expect(screen.getByText(/Wysłać ofertę · 20\.11\.2026/)).toBeTruthy();
  });

  it("bez prawa edycji nie ma przycisków, a zmiana opiekuna tylko dla uprawnionych", () => {
    const { rerender } = render(
      <OpportunityStepBar opportunity={opportunity() as OpportunityDetail} queue={[]} canEdit={false} canChangeOwner={false} {...handlers} />,
    );
    expect(screen.queryByRole("button", { name: "Zaloguj rozmowę" })).toBeNull();
    rerender(<OpportunityStepBar opportunity={opportunity() as OpportunityDetail} queue={[]} canEdit canChangeOwner={false} {...handlers} />);
    expect(screen.getByRole("button", { name: "Zaloguj rozmowę" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Zmień opiekuna" })).toBeNull();
  });
});

describe("zapis rozmowy", () => {
  const people: CallPerson[] = [
    { value: "map:abc", label: "Anna, CIO", name: "Anna", person_key: "abc" },
    { value: "contact:9", label: "Jan", name: "Jan", contact_id: 9 },
  ];
  const onSaved = vi.fn();
  const onClose = vi.fn();

  it("jeden klik zapisuje wynik przy osobie z mapy", () => {
    logCall.mockImplementation((_input, options) => options.onSuccess());
    render(<CallLogPanel opportunityId={1} people={people} initialPerson="map:abc" onSaved={onSaved} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Nie odebrał" }));
    expect(logCall.mock.calls[0][0]).toEqual({
      opportunity_id: 1,
      outcome: "no_answer",
      person_key: "abc",
      contact_id: undefined,
      note: undefined,
    });
    expect(onSaved).toHaveBeenCalledWith("no_answer", people[0]);
  });

  it("ma sześć wyników", () => {
    render(<CallLogPanel opportunityId={1} people={people} initialPerson="map:abc" onSaved={onSaved} onClose={onClose} />);
    for (const name of ["Dodzwoniłem", "Nie odebrał", "Oddzwonić", "Prosi o ofertę", "Nie teraz", "Nie kontaktować"]) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
  });

  it("„Nie kontaktować” pyta przed zapisem i nie otwiera kroku", async () => {
    askConfirm.mockResolvedValueOnce(true);
    logCall.mockImplementation((_input, options) => options.onSuccess());
    render(<CallLogPanel opportunityId={1} people={people} initialPerson="contact:9" onSaved={onSaved} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Nie kontaktować" }));
    await waitFor(() => expect(logCall).toHaveBeenCalled());
    expect(askConfirm.mock.calls[0][0].confirmLabel).toBe("Zapisz sprzeciw");
    expect(logCall.mock.calls[0][0].outcome).toBe("do_not_contact");
    expect(logCall.mock.calls[0][0].contact_id).toBe(9);
    expect(onSaved).toHaveBeenCalledWith("do_not_contact", people[1]);
  });

  it("odmowa w oknie potwierdzenia nic nie zapisuje", async () => {
    askConfirm.mockResolvedValueOnce(false);
    render(<CallLogPanel opportunityId={1} people={people} initialPerson="contact:9" onSaved={onSaved} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Nie kontaktować" }));
    await waitFor(() => expect(askConfirm).toHaveBeenCalled());
    expect(logCall).not.toHaveBeenCalled();
  });

  it("sprzeciw wymaga osoby", () => {
    render(<CallLogPanel opportunityId={1} people={[]} initialPerson="" onSaved={onSaved} onClose={onClose} />);
    expect((screen.getByRole("button", { name: "Nie kontaktować" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("błąd zapisu pokazuje komunikat i nie idzie dalej", () => {
    logCall.mockImplementation((_input, options) => options.onError({ response: { data: { detail: "Ta osoba zgłosiła sprzeciw." } } }));
    render(<CallLogPanel opportunityId={1} people={people} initialPerson="map:abc" onSaved={onSaved} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Dodzwoniłem" }));
    expect(showError).toHaveBeenCalledWith("Ta osoba zgłosiła sprzeciw.");
    expect(onSaved).not.toHaveBeenCalled();
  });
});

describe("„Co dalej i kiedy”", () => {
  it("zakłada zadanie przy szansie, a przypisanie zostawia regule opiekuna", () => {
    const onClose = vi.fn();
    createActivity.mockImplementation((_input, options) => options.onSuccess());
    render(<NextStepDialog opportunityId={4} outcome="no_answer" personName="Anna" onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Zapisz krok" }));
    const payload = createActivity.mock.calls[0][0];
    expect(payload.kind).toBe("task");
    expect(payload.opportunity_id).toBe(4);
    expect(payload.subject).toBe("Zadzwonić ponownie");
    expect(payload.assignee_user_id).toBeUndefined();
    expect(Date.parse(payload.due_at)).toBeGreaterThan(Date.now());
    expect(onClose).toHaveBeenCalled();
  });

  it("bez treści nie zapisze", () => {
    render(<NextStepDialog opportunityId={4} outcome={null} personName={null} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Co trzeba zrobić"), { target: { value: "  " } });
    expect((screen.getByRole("button", { name: "Zapisz krok" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("błąd zostawia okno otwarte", () => {
    const onClose = vi.fn();
    createActivity.mockImplementation((_input, options) => options.onError(new Error("x")));
    render(<NextStepDialog opportunityId={4} outcome={null} personName={null} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Zapisz krok" }));
    expect(showError).toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
});
