import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  addToBlacklist: vi.fn(),
  removeFromBlacklist: vi.fn(),
  clientsLookup: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  candidatesApi: {
    addToBlacklist: mocks.addToBlacklist,
    removeFromBlacklist: mocks.removeFromBlacklist,
  },
  phase5Api: { clientsLookup: mocks.clientsLookup },
}));
const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

import {
  BlacklistDialog,
  BlacklistNotice,
  BlacklistRemoveDialog,
  blacklistMetaLine,
  blacklistReasonLine,
  canRemoveBlacklist,
} from "../BlacklistDialogs";
import { useAuthStore, type User } from "@/store/auth";

function userWithRole(role: string): User {
  return { id: 1, email: `${role}@example.com`, name: role, role, roles: [role], is_active: true } as unknown as User;
}

function httpError(status: number, detail: unknown) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: { detail } } });
}

let queryClient: QueryClient;

function wrap(node: ReactNode) {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>);
}

function renderDialog(props: { alreadyBlacklisted?: boolean } = {}) {
  const onOpenChange = vi.fn();
  const onDone = vi.fn();
  wrap(
    <BlacklistDialog
      candidateId={7}
      candidateName="Anna Nowak"
      open
      onOpenChange={onOpenChange}
      onDone={onDone}
      {...props}
    />,
  );
  return { onOpenChange, onDone };
}

const SUBMIT = { name: "Dodaj do czarnej listy" };

beforeEach(() => {
  vi.clearAllMocks();
  mocks.clientsLookup.mockResolvedValue({
    data: [
      { id: 3, name: "Bank Przykładowy" },
      { id: 4, name: "Ubezpieczenia Testowe" },
    ],
  });
  mocks.addToBlacklist.mockResolvedValue({ data: {} });
  mocks.removeFromBlacklist.mockResolvedValue({ data: { status: "active", blacklist: null } });
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null } as never);
});

describe("BlacklistDialog — „Czarna lista…” (17.10.2026)", () => {
  it("dwa wybory, powód wymagany: przycisk czeka na 5 znaków i zapisuje czarną listę „u nas”", async () => {
    const user = userEvent.setup();
    const { onOpenChange, onDone } = renderDialog();

    expect(screen.getByRole("heading", { name: "Czarna lista — Anna Nowak" })).toBeInTheDocument();
    expect(screen.getByText("Wybierz, gdzie nie współpracujemy z tą osobą.")).toBeInTheDocument();
    const global = screen.getByRole("radio", { name: /U nas — nie współpracujemy z tą osobą/ });
    expect(global).toBeChecked();
    expect(screen.getByRole("radio", { name: /U klienta — nie proponować do:/ })).not.toBeChecked();
    expect(
      screen.getByText("Znika z wyszukiwania pod rekrutację i nie da się jej dodać do żadnej rekrutacji."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Zdjąć czarną listę „u nas” może Delivery Lead/)).toBeInTheDocument();

    const submit = screen.getByRole("button", SUBMIT);
    expect(submit).toBeDisabled();
    const reason = screen.getByLabelText("Powód");
    await user.type(reason, "  abc ");
    // Spacje wokół nie liczą się do minimum.
    expect(submit).toBeDisabled();
    await user.type(reason, "def");
    expect(submit).toBeEnabled();

    await user.click(submit);
    await waitFor(() => expect(mocks.addToBlacklist).toHaveBeenCalledTimes(1));
    expect(mocks.addToBlacklist).toHaveBeenCalledWith(7, {
      scope: "global",
      client_id: null,
      reason: "abc def",
    });
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(toast.showSuccess).toHaveBeenCalledWith("Dodano do czarnej listy");
  });

  it("po zapisie odświeża profil, podgląd, listę kandydatów, konflikty i oś czasu", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    await user.type(screen.getByLabelText("Powód"), "nie przyszedł na start");
    await user.click(screen.getByRole("button", SUBMIT));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    const keys = invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
    for (const key of [
      ["candidate", 7],
      ["candidate-quick-view", 7],
      ["candidate-timeline", 7],
      ["candidates-v2"],
      ["conflicts"],
    ]) {
      expect(keys).toContain(JSON.stringify(key));
    }
  });

  it("„U klienta”: bez wybranego klienta nie da się zapisać, a zapis wysyła klienta", async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole("radio", { name: /U klienta — nie proponować do:/ }));
    await user.type(screen.getByLabelText("Powód"), "konflikt z managerem po projekcie");
    const submit = screen.getByRole("button", SUBMIT);
    expect(submit).toBeDisabled();

    await screen.findByRole("option", { name: "Bank Przykładowy" });
    await user.selectOptions(screen.getByRole("combobox", { name: "Klient" }), "3");
    expect(submit).toBeEnabled();
    expect(screen.getByText("Ostrzeżenie z powodem przy rekrutacjach tego klienta. Nic nie blokuje.")).toBeInTheDocument();

    await user.click(submit);
    await waitFor(() =>
      expect(mocks.addToBlacklist).toHaveBeenCalledWith(7, {
        scope: "client",
        client_id: 3,
        reason: "konflikt z managerem po projekcie",
      }),
    );
    await waitFor(() =>
      expect(toast.showSuccess).toHaveBeenCalledWith("Dodano do czarnej listy u klienta Bank Przykładowy"),
    );
  });

  it("wybór klienta z listy sam przełącza na „U klienta”", async () => {
    const user = userEvent.setup();
    renderDialog();
    await screen.findByRole("option", { name: "Ubezpieczenia Testowe" });
    await user.selectOptions(screen.getByRole("combobox", { name: "Klient" }), "4");
    expect(screen.getByRole("radio", { name: /U klienta — nie proponować do:/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /U nas — nie współpracujemy/ })).not.toBeChecked();
  });

  it("osoba już na czarnej liście u nas: wybór „U nas” wyłączony z wyjaśnieniem", () => {
    renderDialog({ alreadyBlacklisted: true });
    const global = screen.getByRole("radio", { name: /U nas — nie współpracujemy z tą osobą/ });
    expect(global).toBeDisabled();
    expect(global).not.toBeChecked();
    expect(screen.getByRole("radio", { name: /U klienta — nie proponować do:/ })).toBeChecked();
    expect(screen.getByText("Osoba jest już na czarnej liście u nas.")).toBeInTheDocument();
  });

  it("odmowa serwera zostaje w oknie jako zdanie, okno się nie zamyka", async () => {
    const user = userEvent.setup();
    mocks.addToBlacklist.mockRejectedValue(httpError(409, { code: "already_blacklisted" }));
    const { onOpenChange, onDone } = renderDialog();
    await user.type(screen.getByLabelText("Powód"), "drugi raz to samo");
    await user.click(screen.getByRole("button", SUBMIT));
    expect(await screen.findByRole("alert")).toHaveTextContent("Osoba jest już na czarnej liście u nas.");
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    expect(onDone).not.toHaveBeenCalled();
  });

  it("409 przy kliencie bez zdania z serwera mówi, że ten klient już jest", async () => {
    const user = userEvent.setup();
    mocks.addToBlacklist.mockRejectedValue(httpError(409, { code: "client_blacklist_exists" }));
    renderDialog();
    await screen.findByRole("option", { name: "Bank Przykładowy" });
    await user.selectOptions(screen.getByRole("combobox", { name: "Klient" }), "3");
    await user.type(screen.getByLabelText("Powód"), "powód dłuższy niż pięć");
    await user.click(screen.getByRole("button", SUBMIT));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Ta osoba jest już na czarnej liście u tego klienta.",
    );
  });
});

describe("BlacklistRemoveDialog", () => {
  function renderRemove() {
    const onOpenChange = vi.fn();
    wrap(
      <BlacklistRemoveDialog candidateId={7} candidateName="Anna Nowak" open onOpenChange={onOpenChange} />,
    );
    return { onOpenChange };
  }

  it("powód wymagany, zapis woła zdjęcie z powodem", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderRemove();
    const submit = screen.getByRole("button", { name: "Zdejmij z czarnej listy" });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText("Powód"), "abcd");
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText("Powód"), "e — wyjaśnione");
    await user.click(submit);
    await waitFor(() =>
      expect(mocks.removeFromBlacklist).toHaveBeenCalledWith(7, { reason: "abcde — wyjaśnione" }),
    );
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(toast.showSuccess).toHaveBeenCalledWith("Zdjęto z czarnej listy");
  });

  it("odmowa 403 i 409 zostaje w oknie", async () => {
    const user = userEvent.setup();
    mocks.removeFromBlacklist.mockRejectedValueOnce(httpError(409, { code: "not_blacklisted" }));
    renderRemove();
    await user.type(screen.getByLabelText("Powód"), "już zdjęte?");
    await user.click(screen.getByRole("button", { name: "Zdejmij z czarnej listy" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("nie jest już na czarnej liście");
  });
});

describe("BlacklistNotice — baner w profilu", () => {
  const entry = {
    since: "2026-10-17T08:30:00Z",
    by_user_id: 5,
    by_name: "Anna Rekruterka",
    reason: "zrezygnował dzień przed startem u klienta, 03.2026",
  };

  it("kto, kiedy i dlaczego", () => {
    wrap(<BlacklistNotice candidateId={7} candidateName="Jan Kowalski" blacklist={entry} />);
    const notice = screen.getByTestId("blacklist-notice");
    expect(notice).toHaveTextContent("Czarna lista — nie współpracujemy z tą osobą");
    expect(notice).toHaveTextContent("Od 17.10.2026 · dodał(a) Anna Rekruterka");
    expect(notice).toHaveTextContent("Powód: zrezygnował dzień przed startem u klienta, 03.2026");
  });

  it("wpis sprzed 17.10.2026 (same null) mówi, że powodu nie zapisano", () => {
    wrap(
      <BlacklistNotice
        candidateId={7}
        candidateName="Jan Kowalski"
        blacklist={{ since: null, by_user_id: null, by_name: null, reason: null }}
      />,
    );
    const notice = screen.getByTestId("blacklist-notice");
    expect(notice).toHaveTextContent("Powód nie został zapisany (wpis sprzed 17.10.2026).");
    expect(notice).not.toHaveTextContent("Od ");
  });

  it("„Zdejmij…” tylko dla admina, Delivery Leada i Head of Recruitment", () => {
    useAuthStore.setState({ user: userWithRole("recruiter"), realUser: null } as never);
    const view = wrap(<BlacklistNotice candidateId={7} candidateName="Jan Kowalski" blacklist={entry} />);
    expect(screen.queryByRole("button", { name: "Zdejmij…" })).toBeNull();
    view.unmount();

    for (const role of ["admin", "delivery_lead", "head_of_recruitment"]) {
      useAuthStore.setState({ user: userWithRole(role), realUser: null } as never);
      const v = wrap(<BlacklistNotice candidateId={7} candidateName="Jan Kowalski" blacklist={entry} />);
      expect(screen.getByRole("button", { name: "Zdejmij…" })).toBeInTheDocument();
      v.unmount();
    }
  });

  it("„Zdejmij…” otwiera okno zdjęcia z powodem", async () => {
    useAuthStore.setState({ user: userWithRole("admin"), realUser: null } as never);
    wrap(<BlacklistNotice candidateId={7} candidateName="Jan Kowalski" blacklist={entry} />);
    fireEvent.click(screen.getByRole("button", { name: "Zdejmij…" }));
    expect(
      await screen.findByRole("heading", { name: "Zdjąć z czarnej listy — Jan Kowalski?" }),
    ).toBeInTheDocument();
  });

  it("podgląd cudzego konta nie zdejmuje czarnej listy", () => {
    expect(canRemoveBlacklist(userWithRole("admin"), true)).toBe(false);
    expect(canRemoveBlacklist(userWithRole("admin"), false)).toBe(true);
    expect(canRemoveBlacklist(userWithRole("recruiter"), false)).toBe(false);
    expect(canRemoveBlacklist(null, false)).toBe(false);
  });
});

describe("linie wpisu czarnej listy", () => {
  it("pomija człony, których nie znamy", () => {
    expect(blacklistMetaLine({ since: "2026-10-17T08:30:00Z", by_user_id: null, by_name: null, reason: "x" })).toBe(
      "Od 17.10.2026",
    );
    expect(blacklistMetaLine({ since: null, by_user_id: 1, by_name: "Ola", reason: "x" })).toBe("dodał(a) Ola");
    expect(blacklistMetaLine(null)).toBeNull();
    expect(blacklistReasonLine({ since: null, by_user_id: null, by_name: null, reason: "  " })).toBe(
      "Powód nie został zapisany (wpis sprzed 17.10.2026).",
    );
  });
});
