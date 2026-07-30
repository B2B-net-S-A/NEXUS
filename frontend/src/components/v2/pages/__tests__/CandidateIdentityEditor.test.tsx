import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import {
  IdentityEditor,
  type IdentityEditorCandidate,
} from "../CandidateIdentityEditor";

// Mock the axios instance — IdentityEditor PATCHes via the default export of
// @/lib/api and formats errors via the named `extractErrorMsg`.
const patchMock = vi.fn((..._args: unknown[]) => Promise.resolve({ data: {} }));
vi.mock("@/lib/api", () => ({
  default: { patch: (...args: unknown[]) => patchMock(...args) },
  extractErrorMsg: (e: unknown) => String(e),
}));

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
  return { onClose };
}

beforeEach(() => {
  patchMock.mockClear();
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

  it("puste e-mail i telefon wysyła jako null (nie pusty string)", async () => {
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
      email: null,
      phone: null,
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
});
