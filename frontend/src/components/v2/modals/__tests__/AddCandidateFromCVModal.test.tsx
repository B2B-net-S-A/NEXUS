import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AddCandidateFromCVModal } from "@/components/v2/modals/AddCandidateFromCVModal";
import api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/lib/celebrate", () => ({ celebrate: vi.fn() }));

const apiPost = vi.mocked(api.post);

function conflict(reason: string) {
  return {
    response: {
      status: 409,
      data: {
        detail: {
          detail: "Kandydat wygląda na duplikat istniejącego rekordu.",
          existing_candidate_id: 41,
          matches: [
            {
              candidate_id: 41,
              name: "Anna",
              lastname: "Nowak",
              email: "anna.nowak@firma.pl",
              match_score: 1,
              match_reasons: [reason],
            },
          ],
        },
      },
    },
  };
}

function callsTo(url: string) {
  return apiPost.mock.calls.filter(([called]) => String(called).startsWith(url));
}

async function uploadCv(user: ReturnType<typeof userEvent.setup>) {
  const onAdded = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AddCandidateFromCVModal open onOpenChange={vi.fn()} onAdded={onAdded} />
    </QueryClientProvider>,
  );
  const file = new File(["%PDF-1.4"], "anna-nowak.pdf", { type: "application/pdf" });
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
  await user.click(screen.getByRole("button", { name: /Parsuj CV/ }));
  return { onAdded };
}

// 12.10.2026 (decyzja Artura): ta sama osoba = ten sam e-mail. Okno pokazywało
// listę „podobnych” z „match: 95%” i „Zapisz mimo to”, które przy tym samym
// e-mailu serwer i tak odrzucał.
describe("AddCandidateFromCVModal — kandydat już jest w bazie", () => {
  beforeEach(() => {
    apiPost.mockReset();
  });

  it("ten sam e-mail: dodaje CV do profilu jednym żądaniem, bez „Zapisz mimo to”", async () => {
    apiPost.mockImplementation((url: string) =>
      url.startsWith("/api/candidates/from-cv")
        ? Promise.reject(conflict("email_exact"))
        : Promise.resolve({ data: { id: 501 } } as never),
    );
    const user = userEvent.setup();
    const { onAdded } = await uploadCv(user);

    expect(await screen.findByText(/Anna Nowak · anna.nowak@firma.pl/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zapisz mimo to" })).toBeNull();
    expect(screen.queryByText(/match:/)).toBeNull();
    expect(screen.getByRole("link", { name: "Otwórz profil" })).toHaveAttribute("href", "/candidates/41");

    await user.click(screen.getByRole("button", { name: "Dodaj to CV do profilu" }));

    await waitFor(() => expect(callsTo("/api/candidates/41/documents")).toHaveLength(1));
    const body = callsTo("/api/candidates/41/documents")[0][1] as FormData;
    expect(body.get("document_kind")).toBe("cv");
    expect(body.get("is_primary")).toBe("true");
    // W rekrutacji ta osoba trafia do „Nowych” — jak nowy kandydat z CV.
    await waitFor(() => expect(onAdded).toHaveBeenCalledWith(41));
    expect(await screen.findByText("CV dodane do profilu")).toBeInTheDocument();
  });

  it("ten sam plik: nie ma czego dodawać, „Zapisz mimo to” czyta z force", async () => {
    apiPost.mockImplementation((url: string) =>
      url === "/api/candidates/from-cv"
        ? Promise.reject(conflict("identical_file"))
        : Promise.resolve({
            data: { candidate: { id: 77, name: "Anna", lastname: "Nowak" }, confidence: {} },
          } as never),
    );
    const user = userEvent.setup();
    await uploadCv(user);

    expect(await screen.findByText("To CV jest już w profilu")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dodaj to CV do profilu" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Zapisz mimo to" }));

    await waitFor(() => expect(callsTo("/api/candidates/from-cv?force=true")).toHaveLength(1));
  });
});
