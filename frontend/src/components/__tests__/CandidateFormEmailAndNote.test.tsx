/**
 * Runda 10 — formularz kandydata:
 *  - F05: 422 dla e-maila pokazuje polskie zdanie PRZY polu Email (z fokusem
 *    na nim), a nie surowy angielski tekst walidatora na górze formularza;
 *    wpisane dane zostają.
 *  - F-extra: pole „Notatki” zapisuje się jako notatka kandydata (do 27.09
 *    `candidateFormToPayload` go nie wysyłał i tekst ginął bez słowa).
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AddCandidateModal, EditCandidateModal } from "@/components/AppShell";
import api, { phase5Api } from "@/lib/api";
import { emailFieldError } from "@/lib/email-field-error";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/candidates",
}));
vi.mock("@/components/jobs/AutoAssignedCollaborators", () => ({
  AutoAssignedCollaborators: () => null,
}));
vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  aiWriterApi: {},
  candidateProfileApi: { updateLocation: vi.fn() },
  phase5Api: { clientsLookup: vi.fn() },
  pipelineTemplatesApi: { list: vi.fn() },
  requestHistoryApi: { preview: vi.fn() },
  clientTeamApi: { get: vi.fn() },
}));

const apiPost = vi.mocked(api.post);
const apiPatch = vi.mocked(api.patch);

const RESERVED_DOMAIN_422 = {
  response: {
    status: 422,
    data: {
      detail: [
        {
          type: "value_error",
          loc: ["body", "email"],
          msg: "value is not a valid email address: The domain name example.invalid is a special-use or reserved name that cannot be used with email.",
          input: "qa@example.invalid",
        },
      ],
    },
  },
};

function renderWithClient(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  apiPost.mockReset();
  apiPatch.mockReset();
  vi.mocked(api.get).mockResolvedValue({ data: [] } as never);
  vi.mocked(phase5Api.clientsLookup).mockResolvedValue({ data: [] } as never);
});

describe("emailFieldError", () => {
  it("tłumaczy zastrzeżoną domenę i ignoruje błędy innych pól", () => {
    expect(emailFieldError(RESERVED_DOMAIN_422)).toMatch(/domena jest zastrzeżona/);
    expect(
      emailFieldError({
        response: { status: 422, data: { detail: [{ loc: ["body", "phone"], msg: "x" }] } },
      }),
    ).toBeNull();
    expect(emailFieldError({ response: { status: 409, data: { detail: "x" } } })).toBeNull();
  });
});

describe("AddCandidateModal — błąd e-maila przy polu (F05)", () => {
  it("pokazuje polski komunikat przy Emailu, ustawia fokus i zachowuje dane", async () => {
    apiPost.mockImplementation(async (url: string) => {
      if (url === "/api/candidates/check-duplicates") return { data: [] } as never;
      throw RESERVED_DOMAIN_422;
    });
    const user = userEvent.setup();
    renderWithClient(<AddCandidateModal onClose={vi.fn()} onSuccess={vi.fn()} />);

    fireEvent.change(screen.getByPlaceholderText("Jan"), { target: { value: "Jan" } });
    fireEvent.change(screen.getByPlaceholderText("Kowalski"), { target: { value: "Kowalski" } });
    const email = screen.getByPlaceholderText("jan@mail.pl");
    fireEvent.change(email, { target: { value: "qa@example.invalid" } });
    await user.click(screen.getByRole("button", { name: /Dodaj kandydata/ }));

    const alert = await screen.findByText(/domena jest zastrzeżona/);
    expect(alert).toBeInTheDocument();
    expect(screen.queryByText(/value is not a valid email/)).toBeNull();
    expect(email).toHaveAttribute("aria-invalid", "true");
    expect(email).toHaveAttribute("aria-describedby", alert.id);
    await waitFor(() => expect(document.activeElement).toBe(email));
    expect(screen.getByPlaceholderText("Jan")).toHaveValue("Jan");
    expect(email).toHaveValue("qa@example.invalid");

    fireEvent.change(email, { target: { value: "qa@example.invalidx" } });
    expect(screen.queryByText(/domena jest zastrzeżona/)).toBeNull();
  });
});

describe("Formularz kandydata — notatka nie ginie (F-extra)", () => {
  it("dodanie kandydata zapisuje wpisaną notatkę przy nowym kandydacie", async () => {
    apiPost.mockImplementation(async (url: string) => {
      if (url === "/api/candidates/check-duplicates") return { data: [] } as never;
      if (url === "/api/candidates") return { data: { id: 77 } } as never;
      return { data: { id: 1 } } as never;
    });
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    renderWithClient(<AddCandidateModal onClose={vi.fn()} onSuccess={onSuccess} />);

    fireEvent.change(screen.getByPlaceholderText("Jan"), { target: { value: "Jan" } });
    fireEvent.change(screen.getByPlaceholderText("Kowalski"), { target: { value: "Kowalski" } });
    fireEvent.change(screen.getByPlaceholderText("Dodatkowe informacje..."), { target: { value: "  Dzwonić po 16  " } });
    await user.click(screen.getByRole("button", { name: /Dodaj kandydata/ }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith("Kandydat dodany pomyślnie"));
    const noteCalls = apiPost.mock.calls.filter(([url]) => url === "/api/notes");
    expect(noteCalls).toHaveLength(1);
    expect(noteCalls[0][1]).toEqual({
      candidate_id: 77,
      content: "Dzwonić po 16",
      note_type: "general",
    });
  });

  it("nieudany zapis notatki mówi o tym, zamiast udawać sukces", async () => {
    apiPost.mockImplementation(async (url: string) => {
      if (url === "/api/notes") throw new Error("boom");
      return { data: { id: 1 } } as never;
    });
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    renderWithClient(
      <EditCandidateModal
        candidate={{ id: 5, name: "Jan", lastname: "Kowalski", tags: [] }}
        onClose={vi.fn()}
        onSuccess={onSuccess}
      />,
    );
    fireEvent.change(screen.getByPlaceholderText("Dodatkowe informacje..."), { target: { value: "Notatka" } });
    await user.click(screen.getByRole("button", { name: /Zapisz zmiany/ }));
    await waitFor(() =>
      expect(onSuccess).toHaveBeenCalledWith(
        expect.stringMatching(/notatki nie udało się zapisać/),
      ),
    );
  });

  it("pusta notatka nie tworzy wpisu", async () => {
    apiPost.mockResolvedValue({ data: { id: 9 } } as never);
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    renderWithClient(
      <EditCandidateModal
        candidate={{ id: 5, name: "Jan", lastname: "Kowalski", tags: [] }}
        onClose={vi.fn()}
        onSuccess={onSuccess}
      />,
    );
    await user.click(screen.getByRole("button", { name: /Zapisz zmiany/ }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith("Kandydat zaktualizowany"));
    expect(apiPost.mock.calls.filter(([url]) => url === "/api/notes")).toHaveLength(0);
  });
});
