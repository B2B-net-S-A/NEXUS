import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ConflictRow } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  deactivate: vi.fn(),
  clientsLookup: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  phase5Api: {
    clientsLookup: mocks.clientsLookup,
    conflicts: {
      list: mocks.list,
      create: mocks.create,
      deactivate: mocks.deactivate,
    },
  },
}));

import { ConflictsWidget } from "@/components/ConflictsWidget";
import { useAuthStore, type User } from "@/store/auth";

function userWithRole(role: "admin" | "delivery_lead" | "recruiter"): User {
  return {
    id: 1,
    email: `${role}@example.com`,
    name: role,
    role,
    roles: [role],
    is_active: true,
  } as unknown as User;
}

function row(overrides: Partial<ConflictRow> = {}): ConflictRow {
  return {
    id: 11,
    candidate_id: 7,
    client_id: 3,
    client_name: "Bank Testowy",
    type: "nda",
    type_label: "NDA / cooling-off",
    reason: "Projekt u konkurencji",
    active: true,
    state: "active",
    expires_at: "2099-10-01T21:59:59Z",
    created_by: 1,
    created_by_name: "Anna Rekruter",
    created_at: "2026-09-01T10:00:00Z",
    deactivated_at: null,
    deactivated_by: null,
    deactivated_by_name: null,
    deactivation_reason: null,
    ...overrides,
  };
}

function httpError(status: number, detail: unknown) {
  return Object.assign(new Error(`HTTP ${status}`), {
    response: { status, data: { detail } },
  });
}

function renderWidget(props: { hideWhenEmpty?: boolean } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ConflictsWidget candidateId={7} {...props} />
    </QueryClientProvider>,
  );
}

describe("ConflictsWidget", () => {
  let alertSpy: { mockRestore: () => void };
  let confirmSpy: { mockRestore: () => void };

  beforeEach(() => {
    vi.clearAllMocks();
    act(() => {
      useAuthStore.setState({ user: userWithRole("admin"), realUser: null, hydrated: true });
    });
    alertSpy = vi.spyOn(window, "alert").mockImplementation(() => undefined);
    confirmSpy = vi.spyOn(window, "confirm").mockImplementation(() => true);
    mocks.clientsLookup.mockResolvedValue({
      data: [
        { id: 3, name: "Bank Testowy" },
        { id: 4, name: "Ubezpieczyciel" },
      ],
    });
    mocks.list.mockResolvedValue({ data: [] });
  });

  afterEach(() => {
    expect(alertSpy).not.toHaveBeenCalled();
    expect(confirmSpy).not.toHaveBeenCalled();
    alertSpy.mockRestore();
    confirmSpy.mockRestore();
  });

  it("a failed load renders an error, never the collapsed empty link — also with hideWhenEmpty", async () => {
    mocks.list.mockRejectedValue(httpError(500, "boom"));
    renderWidget({ hideWhenEmpty: true });
    expect(await screen.findByText("Nie udało się pobrać danych")).toBeInTheDocument();
    expect(screen.queryByText("Brak aktywnych konfliktów.")).not.toBeInTheDocument();
    // Jedyny „Dodaj konflikt" to przełącznik w nagłówku karty, nie zwinięty link.
    expect(screen.getByTestId("conflict-add-toggle")).toBeInTheDocument();
  });

  it("403 renders as missing permissions, not as an empty list", async () => {
    mocks.list.mockRejectedValue(httpError(403, "forbidden"));
    renderWidget();
    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.queryByText("Brak aktywnych konfliktów.")).not.toBeInTheDocument();
  });

  it("a real empty result with hideWhenEmpty collapses to a single add link", async () => {
    renderWidget({ hideWhenEmpty: true });
    const link = await screen.findByRole("button", { name: "Dodaj konflikt" });
    expect(screen.queryByTestId("conflict-add-toggle")).not.toBeInTheDocument();
    fireEvent.click(link);
    expect(await screen.findByTestId("conflict-save")).toBeInTheDocument();
  });

  it("renders rows with type, client and formatted expiry", async () => {
    mocks.list.mockResolvedValue({ data: [row()] });
    renderWidget();
    const item = await screen.findByTestId("conflict-row-11");
    expect(within(item).getByText("NDA / cooling-off")).toBeInTheDocument();
    expect(within(item).getByText("Bank Testowy")).toBeInTheDocument();
    expect(within(item).getByText("wygasa 01.10.2099")).toBeInTheDocument();
    expect(within(item).getByText(/Anna Rekruter/)).toBeInTheDocument();
    expect(mocks.list).toHaveBeenCalledWith(7, true);
  });

  it("validates inline: client required, NDA requires a date — nothing is sent", async () => {
    renderWidget();
    fireEvent.click(await screen.findByTestId("conflict-add-toggle"));
    fireEvent.click(screen.getByTestId("conflict-save"));
    expect(await screen.findByText("Wybierz klienta.")).toHaveAttribute("role", "alert");

    fireEvent.change(screen.getByLabelText("Typ konfliktu"), { target: { value: "nda" } });
    await waitFor(() =>
      expect(screen.getByLabelText("Klient").querySelectorAll("option").length).toBe(3),
    );
    fireEvent.change(screen.getByLabelText("Klient"), { target: { value: "3" } });
    fireEvent.click(screen.getByTestId("conflict-save"));
    expect(await screen.findByText("NDA wymaga daty wygaśnięcia.")).toHaveAttribute(
      "role",
      "alert",
    );
    expect(mocks.create).not.toHaveBeenCalled();
  });

  it("sends a full ISO expiry and refreshes the list after save", async () => {
    mocks.create.mockResolvedValue({ data: row() });
    renderWidget();
    fireEvent.click(await screen.findByTestId("conflict-add-toggle"));
    await waitFor(() =>
      expect(screen.getByLabelText("Klient").querySelectorAll("option").length).toBe(3),
    );
    fireEvent.change(screen.getByLabelText("Klient"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Typ konfliktu"), { target: { value: "nda" } });
    fireEvent.change(screen.getByLabelText(/Data wygaśnięcia/), {
      target: { value: "2099-10-01" },
    });
    fireEvent.change(screen.getByLabelText("Powód"), { target: { value: "  NDA 6 mies.  " } });
    mocks.list.mockResolvedValue({ data: [row()] });
    fireEvent.click(screen.getByTestId("conflict-save"));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    const [candidateId, payload] = mocks.create.mock.calls[0];
    expect(candidateId).toBe(7);
    expect(payload.client_id).toBe(3);
    expect(payload.type).toBe("nda");
    expect(payload.reason).toBe("NDA 6 mies.");
    expect(new Date(payload.expires_at).getDate()).toBe(1);
    expect(payload.expires_at).toMatch(/Z$/);
    expect(await screen.findByTestId("conflict-row-11")).toBeInTheDocument();
    expect(mocks.list.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("shows a 409 detail from the server inline, in Polish", async () => {
    mocks.create.mockRejectedValue(
      httpError(409, "Ten kandydat ma już aktywny konflikt tego typu u tego klienta"),
    );
    renderWidget();
    fireEvent.click(await screen.findByTestId("conflict-add-toggle"));
    await waitFor(() =>
      expect(screen.getByLabelText("Klient").querySelectorAll("option").length).toBe(3),
    );
    fireEvent.change(screen.getByLabelText("Klient"), { target: { value: "3" } });
    fireEvent.click(screen.getByTestId("conflict-save"));
    const error = await screen.findByText(
      "Ten kandydat ma już aktywny konflikt tego typu u tego klienta",
    );
    expect(error).toHaveAttribute("role", "alert");
    expect(screen.getByTestId("conflict-save")).toBeInTheDocument();
  });

  it("a 422 with a validation array still renders text, not a crash", async () => {
    mocks.create.mockRejectedValue(
      httpError(422, [{ loc: ["body", "expires_at"], msg: "Data wygaśnięcia musi być w przyszłości.", type: "value_error" }]),
    );
    renderWidget();
    fireEvent.click(await screen.findByTestId("conflict-add-toggle"));
    await waitFor(() =>
      expect(screen.getByLabelText("Klient").querySelectorAll("option").length).toBe(3),
    );
    fireEvent.change(screen.getByLabelText("Klient"), { target: { value: "4" } });
    fireEvent.click(screen.getByTestId("conflict-save"));
    expect(await screen.findByText(/Data wygaśnięcia musi być w przyszłości/)).toBeInTheDocument();
  });

  it("deactivates inline with a reason (min 3 chars), cancel restores the row", async () => {
    mocks.list.mockResolvedValue({ data: [row()] });
    mocks.deactivate.mockResolvedValue({
      data: { ok: true, ...row({ active: false, state: "inactive" }) },
    });
    renderWidget();
    const item = await screen.findByTestId("conflict-row-11");

    fireEvent.click(within(item).getByRole("button", { name: "Dezaktywuj" }));
    const submit = within(item).getByRole("button", { name: "Dezaktywuj" });
    expect(submit).toBeDisabled();
    fireEvent.click(within(item).getByRole("button", { name: "Anuluj" }));
    expect(within(item).queryByLabelText("Powód dezaktywacji")).not.toBeInTheDocument();

    fireEvent.click(within(item).getByRole("button", { name: "Dezaktywuj" }));
    const input = within(item).getByLabelText("Powód dezaktywacji");
    fireEvent.change(input, { target: { value: "ab" } });
    expect(within(item).getByRole("button", { name: "Dezaktywuj" })).toBeDisabled();
    fireEvent.change(input, { target: { value: "NDA zakończone wcześniej" } });
    mocks.list.mockResolvedValue({ data: [] });
    fireEvent.click(within(item).getByRole("button", { name: "Dezaktywuj" }));

    await waitFor(() =>
      expect(mocks.deactivate).toHaveBeenCalledWith(11, { reason: "NDA zakończone wcześniej" }),
    );
    expect(await screen.findByText("Brak aktywnych konfliktów.")).toBeInTheDocument();
  });

  it("a failed deactivation shows the server detail inline", async () => {
    mocks.list.mockResolvedValue({ data: [row()] });
    mocks.deactivate.mockRejectedValue(httpError(409, "Ten konflikt jest już nieaktywny."));
    renderWidget();
    const item = await screen.findByTestId("conflict-row-11");
    fireEvent.click(within(item).getByRole("button", { name: "Dezaktywuj" }));
    fireEvent.change(within(item).getByLabelText("Powód dezaktywacji"), {
      target: { value: "powód" },
    });
    fireEvent.click(within(item).getByRole("button", { name: "Dezaktywuj" }));
    expect(await within(item).findByText("Ten konflikt jest już nieaktywny.")).toHaveAttribute(
      "role",
      "alert",
    );
  });

  it("'Pokaż nieaktywne' asks for all rows and shows who, when and why", async () => {
    mocks.list.mockImplementation(async (_id: number, activeOnly: boolean) => ({
      data: activeOnly
        ? []
        : [
            row({
              id: 12,
              active: false,
              state: "inactive",
              deactivated_at: "2026-09-10T08:00:00Z",
              deactivated_by_name: "Piotr DL",
              deactivation_reason: "Klient zgodził się na rekrutację",
            }),
          ],
    }));
    renderWidget();
    expect(await screen.findByText("Brak aktywnych konfliktów.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pokaż nieaktywne" }));

    const item = await screen.findByTestId("conflict-row-12");
    expect(mocks.list).toHaveBeenCalledWith(7, false);
    expect(within(item).getByText("Nieaktywny")).toBeInTheDocument();
    expect(
      within(item).getByText(/Dezaktywowano 10\.09\.2026 przez Piotr DL — Klient zgodził się/),
    ).toBeInTheDocument();
    expect(within(item).queryByRole("button", { name: "Dezaktywuj" })).not.toBeInTheDocument();
  });

  it("a role without write access sees the list but no add or deactivate controls", async () => {
    act(() => {
      useAuthStore.setState({ user: userWithRole("recruiter"), realUser: null, hydrated: true });
    });
    mocks.list.mockResolvedValue({ data: [row()] });
    renderWidget();
    expect(await screen.findByText("Bank Testowy")).toBeInTheDocument();
    expect(screen.queryByTestId("conflict-add-toggle")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dezaktywuj" })).not.toBeInTheDocument();
  });

  it("with hideWhenEmpty an empty list renders nothing for a role that cannot add", async () => {
    act(() => {
      useAuthStore.setState({ user: userWithRole("recruiter"), realUser: null, hydrated: true });
    });
    mocks.list.mockResolvedValue({ data: [] });
    const { container } = renderWidget({ hideWhenEmpty: true });
    await waitFor(() => expect(mocks.list).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
