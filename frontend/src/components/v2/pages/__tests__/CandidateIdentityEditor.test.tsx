import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import {
  IdentityEditor,
  type IdentityEditorCandidate,
  type IdentitySyncState,
} from "../CandidateIdentityEditor";

// Mock the axios instance — IdentityEditor PATCHes ordinary changes and POSTs
// an explicit, confirmation-gated restore from Traffit.
const patchMock = vi.fn();
const postMock = vi.fn();
const getMock = vi.fn();
vi.mock("@/lib/api", () => ({
  default: {
    patch: (...args: unknown[]) => patchMock(...args),
    post: (...args: unknown[]) => postMock(...args),
    get: (...args: unknown[]) => getMock(...args),
  },
  extractErrorMsg: (e: unknown) =>
    e instanceof Error ? e.message : String(e),
}));

const manualNameSync: IdentitySyncState = {
  name: {
    owner: "nexus",
    manual_lock: true,
    traffit_value: "Anna",
    can_restore: true,
    overridden_at: "2026-08-28T12:00:00+00:00",
    override_token: "name-v1",
  },
  lastname: {
    owner: "traffit",
    manual_lock: false,
    traffit_value: "Kowalska",
    can_restore: false,
  },
};

const manualLastnameSync: IdentitySyncState = {
  name: {
    owner: "traffit",
    manual_lock: false,
    traffit_value: "Anna",
    can_restore: false,
  },
  lastname: {
    owner: "nexus",
    manual_lock: true,
    traffit_value: "Kowalska",
    can_restore: true,
    overridden_at: "2026-08-28T12:00:00+00:00",
    override_token: "lastname-v1",
  },
};

function renderEditor(
  overrides: Partial<IdentityEditorCandidate> = {},
  onClose = vi.fn(),
) {
  const candidate: IdentityEditorCandidate = {
    id: 42,
    name: "?",
    lastname: "?",
    email: null,
    phone: null,
    ...overrides,
  };
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <IdentityEditor candidate={candidate} onClose={onClose} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { onClose, queryClient: qc };
}

beforeEach(() => {
  patchMock.mockReset();
  patchMock.mockResolvedValue({ data: {} });
  postMock.mockReset();
  postMock.mockResolvedValue({ data: {} });
  getMock.mockReset();
});

describe("IdentityEditor", () => {
  it("utrzymuje cele dotykowe formularza nagłówka na poziomie co najmniej 44px", () => {
    renderEditor();

    for (const input of screen.getAllByRole("textbox")) {
      expect(input.classList.contains("min-h-11")).toBe(true);
    }
    for (const name of ["Zapisz", "Anuluj"]) {
      const button = screen.getByRole("button", { name });
      expect(button.classList.contains("min-h-11")).toBe(true);
      expect(button.classList.contains("min-w-11")).toBe(true);
    }
  });

  it("zapisuje przycięte imię, nazwisko, e-mail i telefon", async () => {
    const { onClose } = renderEditor();

    fireEvent.change(screen.getByPlaceholderText("Jan"), {
      target: { value: "  Anna  " },
    });
    fireEvent.change(screen.getByPlaceholderText("Kowalski"), {
      target: { value: "Nowak" },
    });
    fireEvent.change(screen.getByPlaceholderText("jan.kowalski@firma.pl"), {
      target: { value: "anna.nowak@firma.pl" },
    });
    fireEvent.change(screen.getByPlaceholderText("+48 500 600 700"), {
      target: { value: "+48 600 700 800" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() => expect(patchMock).toHaveBeenCalledTimes(1));
    expect(patchMock).toHaveBeenCalledWith("/api/candidates/42", {
      name: "Anna",
      lastname: "Nowak",
      email: "anna.nowak@firma.pl",
      phone: "+48 600 700 800",
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("nie wysyła niezmienionych pustych danych kontaktowych", async () => {
    // "?" placeholder candidate with no contact details — recruiter fills only
    // the name. Empty email must become null so the backend EmailStr validator
    // doesn't 422 on "".
    renderEditor();

    fireEvent.change(screen.getByPlaceholderText("Jan"), {
      target: { value: "Jan" },
    });
    fireEvent.change(screen.getByPlaceholderText("Kowalski"), {
      target: { value: "Testowy" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() => expect(patchMock).toHaveBeenCalledTimes(1));
    expect(patchMock).toHaveBeenCalledWith("/api/candidates/42", {
      name: "Jan",
      lastname: "Testowy",
    });
  });

  it("blokuje zapis bez imienia lub nazwiska", async () => {
    renderEditor({ name: "", lastname: "" });

    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    // No PATCH fired — client-side validation short-circuits before the call.
    await Promise.resolve();
    expect(patchMock).not.toHaveBeenCalled();
    expect(
      await screen.findByText("Imię i nazwisko są wymagane"),
    ).toBeInTheDocument();
  });

  it("pokazuje źródło i ręczną ochronę osobno dla imienia i nazwiska", () => {
    renderEditor({
      name: "Ania",
      lastname: "Kowalska",
      identity_sync: manualNameSync,
    });

    expect(screen.getByText("Ręczna korekta")).toBeInTheDocument();
    expect(screen.getByText("Traffit")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Chronione przed nadpisaniem przez synchronizację z Traffita.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Synchronizowane z Traffita. Zmiana stanie się ręczną korektą.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "Przywróć imię z Traffita" }),
    ).toHaveLength(1);
  });

  it("nie miesza restore z niezapisanymi zmianami formularza", () => {
    renderEditor({
      name: "Anna",
      lastname: "Nowak",
      identity_sync: manualLastnameSync,
    });

    fireEvent.change(screen.getByLabelText("E-mail"), {
      target: { value: "draft@example.com" },
    });

    const restoreButton = screen.getByRole("button", {
      name: "Przywróć nazwisko z Traffita",
    });
    expect(restoreButton).toBeDisabled();
    const reason = screen.getByText(
      "Najpierw zapisz albo anuluj niezapisane zmiany.",
    );
    expect(reason).toBeVisible();
    expect(restoreButton).toHaveAttribute("aria-describedby", reason.id);
  });

  it("potwierdza restore z widocznym porównaniem i wysyła oczekiwany snapshot Traffita", async () => {
    postMock.mockResolvedValue({
      data: {
        id: 42,
        name: "Anna",
        lastname: "Kowalska",
        email: null,
        phone: null,
        identity_sync: {
          name: manualLastnameSync.name,
          lastname: {
            owner: "traffit",
            manual_lock: false,
            traffit_value: "Kowalska",
            can_restore: false,
          },
        },
      } satisfies IdentityEditorCandidate,
    });
    const { onClose, queryClient } = renderEditor({
      name: "Anna",
      lastname: "Nowak",
      identity_sync: manualLastnameSync,
    });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    fireEvent.click(
      screen.getByRole("button", { name: "Przywróć nazwisko z Traffita" }),
    );

    expect(postMock).not.toHaveBeenCalled();
    expect(
      screen.getByRole("heading", {
        name: "Przywrócić nazwisko z Traffita?",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Nowak")).toBeInTheDocument();
    expect(screen.getByText("Kowalska")).toBeInTheDocument();
    expect(
      screen.getByText(/Kolejne synchronizacje z Traffita/),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Potwierdź przywrócenie" }),
    );

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/api/candidates/42/identity/restore-from-traffit",
        {
          fields: ["lastname"],
          expected_current_values: { lastname: "Nowak" },
          expected_traffit_values: { lastname: "Kowalska" },
          expected_override_tokens: {
            lastname: "lastname-v1",
          },
        },
      ),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Nazwisko")).toHaveValue("Kowalska"),
    );
    expect(onClose).not.toHaveBeenCalled();
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["candidate", 42],
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["candidates-v2"],
    });
  });

  it("blokuje formularz i zamknięcie dialogu podczas przywracania", async () => {
    let resolveRestore!: (value: { data: IdentityEditorCandidate }) => void;
    postMock.mockReturnValue(
      new Promise<{ data: IdentityEditorCandidate }>((resolve) => {
        resolveRestore = resolve;
      }),
    );
    renderEditor({
      name: "Anna",
      lastname: "Nowak",
      identity_sync: manualLastnameSync,
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Przywróć nazwisko z Traffita" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Potwierdź przywrócenie" }),
    );

    const pendingButton = await screen.findByRole("button", {
      name: "Przywracanie…",
    });
    expect(pendingButton).toBeDisabled();
    expect(screen.getByLabelText("Nazwisko")).toBeDisabled();
    for (const cancel of screen.getAllByRole("button", { name: "Anuluj" })) {
      expect(cancel).toBeDisabled();
    }

    resolveRestore({
      data: {
        id: 42,
        name: "Anna",
        lastname: "Kowalska",
        identity_sync: {
          ...manualLastnameSync,
          lastname: {
            owner: "traffit",
            manual_lock: false,
            traffit_value: "Kowalska",
            can_restore: false,
          },
        },
      },
    });
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", {
          name: "Przywrócić nazwisko z Traffita?",
        }),
      ).not.toBeInTheDocument(),
    );
  });

  it("zachowuje dialog i pokazuje trwały błąd, gdy restore się nie powiedzie", async () => {
    postMock.mockRejectedValue(new Error("Snapshot Traffita uległ zmianie"));
    renderEditor({
      name: "Anna",
      lastname: "Nowak",
      identity_sync: manualLastnameSync,
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Przywróć nazwisko z Traffita" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Potwierdź przywrócenie" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Snapshot Traffita uległ zmianie",
    );
    expect(
      screen.getByRole("heading", {
        name: "Przywrócić nazwisko z Traffita?",
      }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Nazwisko")).toHaveValue("Nowak");
  });

  it("po konflikcie 409 odświeża snapshot i retry wysyła aktualny token", async () => {
    const conflict = Object.assign(
      new Error("Snapshot Traffita uległ zmianie."),
      { response: { status: 409 } },
    );
    const refreshedSync: IdentitySyncState = {
      ...manualLastnameSync,
      lastname: {
        ...manualLastnameSync.lastname,
        traffit_value: "Kowalska-Nowa",
        overridden_at: "2026-08-28T13:00:00+00:00",
        override_token: "lastname-v2",
      },
    };
    postMock
      .mockRejectedValueOnce(conflict)
      .mockResolvedValueOnce({
        data: {
          id: 42,
          name: "Anna",
          lastname: "Kowalska-Nowa",
          identity_sync: {
            ...refreshedSync,
            lastname: {
              owner: "traffit",
              manual_lock: false,
              traffit_value: "Kowalska-Nowa",
              can_restore: false,
            },
          },
        } satisfies IdentityEditorCandidate,
      });
    getMock.mockResolvedValue({
      data: {
        id: 42,
        name: "Anna",
        lastname: "Nowak po zmianie",
        email: null,
        phone: null,
        identity_sync: refreshedSync,
      } satisfies IdentityEditorCandidate,
    });
    const { queryClient } = renderEditor({
      name: "Anna",
      lastname: "Nowak",
      identity_sync: manualLastnameSync,
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Przywróć nazwisko z Traffita" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Potwierdź przywrócenie" }),
    );

    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith("/api/candidates/42"),
    );
    expect(await screen.findByText("Nowak po zmianie")).toBeInTheDocument();
    expect(screen.getByText("Kowalska-Nowa")).toBeInTheDocument();
    expect(
      screen.getByText(/Profil został odświeżony — sprawdź aktualne wartości/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Nazwisko")).toHaveValue("Nowak po zmianie");
    expect(queryClient.getQueryData(["candidate", 42])).toMatchObject({
      lastname: "Nowak po zmianie",
      identity_sync: refreshedSync,
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Potwierdź przywrócenie" }),
    );

    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(2));
    expect(postMock).toHaveBeenNthCalledWith(
      2,
      "/api/candidates/42/identity/restore-from-traffit",
      {
        fields: ["lastname"],
        expected_current_values: { lastname: "Nowak po zmianie" },
        expected_traffit_values: { lastname: "Kowalska-Nowa" },
        expected_override_tokens: { lastname: "lastname-v2" },
      },
    );
  });
});
