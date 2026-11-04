/**
 * Zrzut zgody sprawdzany przy wgraniu (F37, 27.10.2026, wariant A).
 *
 * Niepasujący zrzut (np. prośba rekrutera zamiast odpowiedzi kandydata)
 * wraca bez pokwitowania: karta pokazuje uwagi i NIE dołącza zgody. „Zapisz
 * mimo to” wysyła ten sam plik jeszcze raz z powodem — dopiero wtedy zgoda
 * trafia pod CV, a powód widzi Delivery Lead w QC CV.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { configure, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";

import { ConsentAttachButton } from "../ConsentAttachButton";

configure({ asyncUtilTimeout: 10000 });

const MISMATCH = {
  consent_token: null,
  filename: "zgoda.png",
  check: {
    status: "mismatch",
    problems: [
      {
        code: "recruiter_request",
        detail: "To prośba o zgodę wysłana do kandydata (nadawca: Anna Rekruterka), a nie jego odpowiedź.",
      },
    ],
    passed: [{ code: "zob", detail: "ZOB-3092 zgadza się z rekrutacją" }],
  },
};

const uploadMock = vi.fn();
const attachMock = vi.fn(async (_id: number, _token: string) => ({ data: {} }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    cvGeneratorApi: {
      uploadConsentForGenerated: (id: number, file: File, reason?: string) => uploadMock(id, file, reason),
      uploadConsentForStage: vi.fn(),
      attachConsent: (id: number, token: string) => attachMock(id, token),
    },
    candidateStageCvApi: { branded: { attachConsent: vi.fn() } },
  };
});

function renderButton(onAttached = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ToastProvider>
        <ConsentAttachButton generatedId={42} hasConsent={false} onAttached={onAttached} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return onAttached;
}

function pick(file: File) {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  fireEvent.change(input);
}

beforeEach(() => {
  uploadMock.mockReset();
  attachMock.mockClear();
});

describe("ConsentAttachButton — sprawdzenie zrzutu", () => {
  it("niepasujący zrzut nie trafia pod CV, a karta mówi dlaczego", async () => {
    uploadMock.mockResolvedValue({ data: MISMATCH });
    const onAttached = renderButton();
    pick(new File(["img"], "zgoda.png", { type: "image/png" }));

    expect(await screen.findByText("To prośba o zgodę, a nie odpowiedź kandydata")).toBeInTheDocument();
    expect(screen.getByText(/nadawca: Anna Rekruterka/)).toBeInTheDocument();
    expect(screen.getByText("ZOB-3092 zgadza się z rekrutacją")).toBeInTheDocument();
    expect(attachMock).not.toHaveBeenCalled();
    expect(onAttached).not.toHaveBeenCalled();
    // Główny przycisk znika — „Wgraj inny zrzut” stoi w uwagach.
    expect(screen.queryByRole("button", { name: /Wgraj zrzut maila/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wgraj inny zrzut" })).toBeInTheDocument();
  });

  it("„zapisz mimo to” wysyła ten sam plik z powodem i dopiero wtedy dołącza zgodę", async () => {
    uploadMock.mockResolvedValueOnce({ data: MISMATCH }).mockResolvedValueOnce({
      data: {
        consent_token: "tok-override",
        filename: "zgoda.png",
        check: { ...MISMATCH.check, override: { reason: "kandydat odpisał z innej skrzynki", by: 7, at: "x" } },
      },
    });
    const onAttached = renderButton();
    const file = new File(["img"], "zgoda.png", { type: "image/png" });
    pick(file);

    fireEvent.click(await screen.findByRole("button", { name: /zapisz mimo to/ }));
    const save = screen.getByRole("button", { name: "Zapisz z powodem" });
    // Bez powodu (min. 5 znaków) zapis jest zablokowany.
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Dlaczego to dobry zrzut/), {
      target: { value: "kandydat odpisał z innej skrzynki" },
    });
    fireEvent.click(save);

    await waitFor(() => expect(onAttached).toHaveBeenCalled());
    expect(uploadMock).toHaveBeenLastCalledWith(42, file, "kandydat odpisał z innej skrzynki");
    expect(attachMock).toHaveBeenCalledWith(42, "tok-override");
  });

  it("pasujący zrzut dołącza się od razu i komunikat mówi, co sprawdzono", async () => {
    uploadMock.mockResolvedValue({
      data: {
        consent_token: "tok-ok",
        filename: "zgoda.png",
        check: { status: "ok", problems: [], passed: [{ code: "zob", detail: "ZOB-3092 zgadza się z rekrutacją" }] },
      },
    });
    const onAttached = renderButton();
    pick(new File(["img"], "zgoda.png", { type: "image/png" }));

    await waitFor(() => expect(onAttached).toHaveBeenCalled());
    expect(attachMock).toHaveBeenCalledWith(42, "tok-ok");
    expect(await screen.findByText(/Zgoda pasuje: ZOB-3092 zgadza się z rekrutacją/)).toBeInTheDocument();
  });
});
