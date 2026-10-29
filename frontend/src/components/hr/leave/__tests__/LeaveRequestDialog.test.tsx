/**
 * Okno nieobecności: jaki ładunek idzie do zapisu (własny wniosek albo wpis
 * za pracownika) i jaki obiekt do podglądu — z wypełnionego formularza.
 * Hooki API zamockowane, `Select` jako natywny `<select>` (Radix w jsdom
 * nie otwiera listy), dane fikcyjne.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import type { LeaveInput, LeavePreview, OnBehalfPerson, SubstituteCandidate } from "@/lib/api/hr-leave";

import { LeaveRequestDialog } from "../LeaveRequestDialog";

const mocks = vi.hoisted(() => ({
  submitOwn: vi.fn(),
  submitFor: vi.fn(),
  attach: vi.fn(),
  preview: vi.fn(),
  blockingReason: null as string | null,
  cproSender: false,
  people: null as null | { data?: unknown; isSuccess?: boolean; isError?: boolean; error?: unknown },
}));

vi.mock("@/lib/api/hr-leave", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/hr-leave")>()),
  useOnBehalfPeople: () => mocks.people ?? { data: PEOPLE, isSuccess: true },
  useSubstitutes: () => ({ data: SUBSTITUTES }),
  useSubmitLeave: () => ({ mutate: mocks.submitOwn, isPending: false }),
  useEnterOnBehalf: () => ({ mutate: mocks.submitFor, isPending: false }),
  useAttachLeaveProof: () => ({ mutate: mocks.attach, isPending: false }),
  useLeavePreview: (input: LeaveInput | null, onBehalfOf: number | null) => {
    mocks.preview(input, onBehalfOf);
    return {
      data: input ? preview(mocks.blockingReason) : undefined,
      isFetching: false,
      isLoading: false,
      isError: false,
    };
  },
}));

vi.mock("@/lib/api/boardTasks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/boardTasks")>()),
  useCproAssigneeOptions: () => ({
    data: [
      { id: 5, name: "Jan Testowy" },
      { id: 9, name: "Ola Przykładowa" },
    ],
    isLoading: false,
    isError: false,
  }),
}));

vi.mock("@/components/ui/select", async () => {
  const ReactModule = await import("react");
  const SelectTrigger = (_props: { id?: string; children?: React.ReactNode }) => null;
  const SelectContent = (_props: { children?: React.ReactNode }) => null;
  const SelectItem = (_props: { value: string; children?: React.ReactNode }) => null;
  const SelectValue = (_props: { placeholder?: string }) => null;
  function Select({
    children,
    value,
    onValueChange,
    disabled,
  }: {
    children: React.ReactNode;
    value?: string;
    onValueChange?: (value: string) => void;
    disabled?: boolean;
  }) {
    const elements = ReactModule.Children.toArray(children).filter(ReactModule.isValidElement);
    const trigger = elements.find((child) => child.type === SelectTrigger) as
      | React.ReactElement<{ id?: string }>
      | undefined;
    const content = elements.find((child) => child.type === SelectContent) as
      | React.ReactElement<{ children?: React.ReactNode }>
      | undefined;
    const items = ReactModule.Children.toArray(content?.props.children).filter(
      ReactModule.isValidElement,
    ) as React.ReactElement<{ value: string; children?: React.ReactNode }>[];
    return (
      <select
        id={trigger?.props.id}
        value={value}
        disabled={disabled}
        onChange={(event) => onValueChange?.(event.target.value)}
      >
        {items.map((item) => (
          <option key={item.props.value} value={item.props.value}>
            {item.props.children}
          </option>
        ))}
      </select>
    );
  }
  return { Select, SelectTrigger, SelectContent, SelectItem, SelectValue };
});

const PEOPLE: OnBehalfPerson[] = [
  { user_id: 7, name: "Anna Przykładowa", employment_type: "uop", department: "Rekrutacja" },
];

const SUBSTITUTES: SubstituteCandidate[] = [
  {
    user_id: 5,
    name: "Jan Testowy",
    job_title: null,
    department: "Rekrutacja",
    same_department: true,
    shared_role: false,
    suggested: true,
  },
];

function preview(blockingReason: string | null): LeavePreview {
  return {
    working_days: ["2026-11-02"],
    days_total: "1.0",
    paid_days: "1.0",
    unpaid_days: "0.0",
    years: [
      {
        year: 2026,
        requested: "1.0",
        paid: "1.0",
        unpaid: "0.0",
        has_pool: true,
        remaining_before: "10.0",
        remaining_after: "9.0",
      },
    ],
    blocking_reason: blockingReason,
    auto_approved: false,
    employment_type: "uop",
    flow: "request",
    approver: "Ewa Przykładowa",
    department_absent: [],
    work: { total: 0, by_kind: [], items: [] },
    substitute_absent: false,
    return_on: null,
    cpro_sender: mocks.cproSender,
  };
}

function open(mode: "self" | "on_behalf") {
  render(
    <ToastProvider>
      <LeaveRequestDialog open onOpenChange={() => undefined} mode={mode} employmentType="uop" />
    </ToastProvider>,
  );
  return screen.getByRole("dialog");
}

function setDate(dialog: HTMLElement, label: "Od" | "Do", value: string) {
  fireEvent.change(within(dialog).getByLabelText(label), { target: { value } });
}

// Debounce podglądu (350 ms) przy obciążonej maszynie.
const SETTLE = { timeout: 3000 };

beforeEach(() => {
  mocks.people = null;
  mocks.submitOwn.mockReset();
  mocks.submitFor.mockReset();
  mocks.attach.mockReset();
  mocks.preview.mockReset();
  mocks.blockingReason = null;
  mocks.cproSender = false;
});

describe("LeaveRequestDialog — ładunek zapisu i podglądu", () => {
  it("własny wniosek: rodzaj, pół dnia, zastępca, notatka, zgoda na przekierowanie i OOF", async () => {
    const user = userEvent.setup();
    const dialog = open("self");

    await user.selectOptions(within(dialog).getByLabelText("Rodzaj"), "on_demand");
    setDate(dialog, "Od", "2026-11-02");
    setDate(dialog, "Do", "2026-11-02");
    await user.selectOptions(within(dialog).getByLabelText("Wymiar"), "afternoon");
    await user.selectOptions(within(dialog).getByLabelText("Zastępca"), "5");
    await user.type(within(dialog).getByLabelText("Notatka"), "  Wyjazd rodzinny  ");
    await user.click(within(dialog).getByRole("checkbox"));
    await user.click(within(dialog).getByRole("button", { name: "Własny tekst autoodpowiedzi w Outlooku" }));
    await user.type(within(dialog).getByLabelText("Autoodpowiedź dla firmy"), " Wracam 3.11. ");
    await user.type(within(dialog).getByLabelText("Autoodpowiedź na zewnątrz"), "   ");

    const save = within(dialog).getByRole("button", { name: "Wyślij do akceptacji" });
    await waitFor(() => expect(save).toBeEnabled(), SETTLE);
    // Podgląd dostaje pola wniosku bez notatki i OOF; własny = bez osoby.
    expect(mocks.preview.mock.lastCall).toEqual([
      {
        leave_type: "on_demand",
        start_date: "2026-11-02",
        end_date: "2026-11-02",
        half_day: "afternoon",
        substitute_user_id: 5,
      },
      null,
    ]);

    await user.click(save);
    expect(mocks.submitFor).not.toHaveBeenCalled();
    expect(mocks.submitOwn).toHaveBeenCalledTimes(1);
    expect(mocks.submitOwn.mock.calls[0][0]).toStrictEqual({
      leave_type: "on_demand",
      start_date: "2026-11-02",
      end_date: "2026-11-02",
      half_day: "afternoon",
      substitute_user_id: 5,
      note: "Wyjazd rodzinny",
      forward_mail_consent: true,
      oof_internal_message: "Wracam 3.11.",
      oof_external_message: null,
    });
  });

  it("wpis za pracownika: bez osoby zablokowany; kilka dni = cały dzień, bez zastępcy i notatki, bez OOF", async () => {
    const user = userEvent.setup();
    const dialog = open("on_behalf");

    // Bez wybranej osoby nie ma czego liczyć ani zapisać.
    expect(within(dialog).getByText("Wybierz osobę, żeby policzyć dni i pulę.")).toBeInTheDocument();
    const save = within(dialog).getByRole("button", { name: "Wpisz nieobecność" });
    expect(save).toBeDisabled();
    expect(mocks.preview).toHaveBeenLastCalledWith(null, null);

    await user.selectOptions(within(dialog).getByLabelText("Osoba"), "7");
    await user.selectOptions(within(dialog).getByLabelText("Rodzaj"), "sick_leave");
    setDate(dialog, "Od", "2026-11-02");
    setDate(dialog, "Do", "2026-11-02");
    await user.selectOptions(within(dialog).getByLabelText("Wymiar"), "morning");
    // Drugi dzień: pół dnia przestaje się liczyć.
    setDate(dialog, "Do", "2026-11-04");
    expect(within(dialog).queryByRole("checkbox")).toBeNull();
    expect(
      within(dialog).queryByRole("button", { name: "Własny tekst autoodpowiedzi w Outlooku" }),
    ).toBeNull();

    await waitFor(() => expect(save).toBeEnabled(), SETTLE);
    expect(mocks.preview.mock.lastCall).toEqual([
      {
        leave_type: "sick_leave",
        start_date: "2026-11-02",
        end_date: "2026-11-04",
        half_day: null,
        substitute_user_id: null,
      },
      7,
    ]);

    await user.click(save);
    expect(mocks.submitOwn).not.toHaveBeenCalled();
    expect(mocks.submitFor).toHaveBeenCalledTimes(1);
    expect(mocks.submitFor.mock.calls[0][0]).toStrictEqual({
      leave_type: "sick_leave",
      start_date: "2026-11-02",
      end_date: "2026-11-04",
      half_day: null,
      substitute_user_id: null,
      note: null,
      user_id: 7,
    });
  });

  it("podgląd z powodem blokady: przycisk zablokowany, nic nie idzie do zapisu", async () => {
    const user = userEvent.setup();
    mocks.blockingReason = "W wybranym okresie nie ma dni roboczych.";
    const dialog = open("self");

    setDate(dialog, "Od", "2026-11-07");
    setDate(dialog, "Do", "2026-11-08");
    await waitFor(
      () =>
        expect(mocks.preview.mock.lastCall?.[0]).toEqual(
          expect.objectContaining({ start_date: "2026-11-07", end_date: "2026-11-08" }),
        ),
      SETTLE,
    );
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "W wybranym okresie nie ma dni roboczych.",
    );
    const save = within(dialog).getByRole("button", { name: "Wyślij do akceptacji" });
    expect(save).toBeDisabled();
    await user.click(save);
    expect(mocks.submitOwn).not.toHaveBeenCalled();
  });
});

describe("LeaveRequestDialog — załącznik do własnego wniosku", () => {
  const proof = () => new File(["%PDF-1.4"], "akt-slubu.pdf", { type: "application/pdf" });

  it("okolicznościowy podpowiada akt; plik idzie do id zapisanego wniosku", async () => {
    const user = userEvent.setup();
    const dialog = open("self");

    await user.selectOptions(within(dialog).getByLabelText("Rodzaj"), "occasional");
    expect(within(dialog).getByText(/akt ślubu, urodzenia albo zgonu/)).toBeInTheDocument();
    await user.upload(within(dialog).getByLabelText("Załącznik (opcjonalnie)"), proof());
    expect(within(dialog).getByText(/akt-slubu\.pdf/)).toBeInTheDocument();

    const save = within(dialog).getByRole("button", { name: "Wyślij do akceptacji" });
    await waitFor(() => expect(save).toBeEnabled(), SETTLE);
    await user.click(save);

    expect(mocks.submitOwn).toHaveBeenCalledTimes(1);
    // Wniosek zapisany → dopiero wtedy plik, do jego id.
    expect(mocks.attach).not.toHaveBeenCalled();
    const { onSuccess } = mocks.submitOwn.mock.calls[0][1] as {
      onSuccess: (row: { id: string; status: string }) => void;
    };
    onSuccess({ id: "r-42", status: "pending" });
    expect(mocks.attach).toHaveBeenCalledTimes(1);
    expect(mocks.attach.mock.calls[0][0].id).toBe("r-42");
    expect(mocks.attach.mock.calls[0][0].file.name).toBe("akt-slubu.pdf");
  });

  it("plik spoza PDF/JPG/PNG nie wchodzi; bez pliku nic nie idzie do załączników", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const dialog = open("self");

    await user.upload(
      within(dialog).getByLabelText("Załącznik (opcjonalnie)"),
      new File(["x"], "akt.docx", { type: "application/msword" }),
    );
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Dozwolone formaty");

    const save = within(dialog).getByRole("button", { name: "Wyślij do akceptacji" });
    await waitFor(() => expect(save).toBeEnabled(), SETTLE);
    await user.click(save);
    const { onSuccess } = mocks.submitOwn.mock.calls[0][1] as {
      onSuccess: (row: { id: string; status: string }) => void;
    };
    onSuccess({ id: "r-43", status: "pending" });
    expect(mocks.attach).not.toHaveBeenCalled();
  });

  it("wpis za pracownika nie ma pola załącznika", () => {
    const dialog = open("on_behalf");
    expect(within(dialog).queryByLabelText("Załącznik (opcjonalnie)")).toBeNull();
  });
});

describe("wpis za pracownika — lista osób (audyt 19.10.2026)", () => {
  it("koordynator samych kontraktorów widzi wyjaśnienie zamiast pustej listy", () => {
    mocks.people = {
      data: [{ user_id: 9, name: "Ola B2B", employment_type: "b2b", department: null, can_enter: false }],
      isSuccess: true,
    };
    const dialog = open("on_behalf");
    expect(
      within(dialog).getByText(/Osoby na B2B i zleceniu zgłaszają nieobecność same/),
    ).toBeInTheDocument();
  });

  it("awaria listy osób to komunikat, nie pusta lista", () => {
    mocks.people = { data: undefined, isError: true, error: new Error("500") };
    const dialog = open("on_behalf");
    expect(within(dialog).getByText("Nie udało się wczytać listy osób.")).toBeInTheDocument();
  });
});

describe("LeaveRequestDialog — osoba od Cpro wskazuje, kto wrzuca (29.10.2026)", () => {
  it("bez wyboru zapis zablokowany; wybór idzie w ładunku, nie w podglądzie", async () => {
    mocks.cproSender = true;
    const user = userEvent.setup();
    const dialog = open("self");
    setDate(dialog, "Od", "2026-11-02");
    setDate(dialog, "Do", "2026-11-03");

    const field = await within(dialog).findByLabelText("Kto wrzuca do Cpro", {}, SETTLE);
    const save = within(dialog).getByRole("button", { name: "Wyślij do akceptacji" });
    // Podgląd przyszedł, ale bez osoby do Cpro wniosku nie da się wysłać.
    await waitFor(() => expect(mocks.preview).toHaveBeenCalled(), SETTLE);
    expect(save).toBeDisabled();

    await user.selectOptions(field, "9");
    await waitFor(() => expect(save).toBeEnabled(), SETTLE);
    expect(mocks.preview.mock.lastCall?.[0]).not.toHaveProperty("cpro_substitute_user_id");
    await user.click(save);
    expect(mocks.submitOwn.mock.calls[0][0]).toMatchObject({ cpro_substitute_user_id: 9 });
  });

  it("pół dnia nie wymaga wyboru", async () => {
    mocks.cproSender = true;
    const user = userEvent.setup();
    const dialog = open("self");
    setDate(dialog, "Od", "2026-11-02");
    setDate(dialog, "Do", "2026-11-02");
    await user.selectOptions(within(dialog).getByLabelText("Wymiar"), "morning");
    const save = within(dialog).getByRole("button", { name: "Wyślij do akceptacji" });
    await waitFor(() => expect(save).toBeEnabled(), SETTLE);
    await user.click(save);
    expect(mocks.submitOwn.mock.calls[0][0]).not.toHaveProperty("cpro_substitute_user_id");
  });

  it("zwykła osoba: pola „Kto wrzuca do Cpro” nie ma", async () => {
    const dialog = open("self");
    setDate(dialog, "Od", "2026-11-02");
    setDate(dialog, "Do", "2026-11-03");
    await waitFor(
      () => expect(within(dialog).getByRole("button", { name: "Wyślij do akceptacji" })).toBeEnabled(),
      SETTLE,
    );
    expect(within(dialog).queryByLabelText("Kto wrzuca do Cpro")).toBeNull();
  });
});
