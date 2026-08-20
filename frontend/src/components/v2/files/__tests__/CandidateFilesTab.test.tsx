import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import api from "@/lib/api";
import { CandidateFilesTab } from "@/components/v2/files/CandidateFilesTab";

const showError = vi.fn();
const showToast = vi.fn();

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  extractErrorMsg: (error: unknown) =>
    (error as { message?: string })?.message ?? "",
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError, showToast }),
}));

vi.mock("@/components/v2/files/FilePreviewModal", async () => {
  const actual = await vi.importActual<
    typeof import("@/components/v2/files/FilePreviewModal")
  >("@/components/v2/files/FilePreviewModal");
  return { ...actual, FilePreviewModal: () => null };
});

let currentRole = "recruiter";

// `getUserRoles` MUSI być w tej fabryce: bramka zakładki idzie przez
// `useCapability` → `hasCapability` (realny `@/lib/capabilities`) →
// `getUserRoles` z TEGO mocka. Bez niego leci TypeError w renderze i pada
// CAŁY plik — objaw wygląda jak zepsuta bramka, przyczyną jest setup testu.
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: { role: string } }) => unknown) =>
    selector({ user: { role: currentRole } }),
  hasRole: (user: { role: string } | null, ...roles: string[]) =>
    !!user && roles.includes(user.role),
  getUserRoles: (user: { role: string; roles?: string[] } | null) =>
    user ? Array.from(new Set([user.role, ...(user.roles ?? [])])) : [],
}));

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CandidateFilesTab candidateId={42} />
    </QueryClientProvider>,
  );
}

function pickFile(file: File) {
  const input = screen.getByTestId(
    "candidate-document-upload-input",
  ) as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
  return input;
}

describe("CandidateFilesTab upload", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    currentRole = "recruiter";
    vi.mocked(api.get).mockResolvedValue({ data: [] });
    vi.mocked(api.post).mockResolvedValue({ data: {} });
  });

  it("shows the uploader on an empty profile — that is when it is needed most", async () => {
    renderTab();

    expect(
      await screen.findByRole("button", { name: /Dodaj plik/ }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/Brak plików\. Dodaj CV, certyfikat/),
    ).toBeInTheDocument();
  });

  it("posts the picked file as multipart with the selected kind", async () => {
    renderTab();
    await screen.findByRole("button", { name: /Dodaj plik/ });

    fireEvent.change(screen.getByLabelText("Rodzaj"), {
      target: { value: "certificate" },
    });
    pickFile(new File(["scan"], "certyfikat.pdf", { type: "application/pdf" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    const [url, body, config] = vi.mocked(api.post).mock.calls[0];
    expect(url).toBe("/api/candidates/42/documents");
    expect(body).toBeInstanceOf(FormData);
    const formData = body as FormData;
    expect((formData.get("file") as File).name).toBe("certyfikat.pdf");
    expect(formData.get("document_kind")).toBe("certificate");
    expect(config).toMatchObject({
      headers: { "Content-Type": "multipart/form-data" },
    });
    await waitFor(() => expect(showToast).toHaveBeenCalled());
  });

  it("uploads several files sequentially and refetches the list once done", async () => {
    renderTab();
    await screen.findByRole("button", { name: /Dodaj plik/ });

    const input = screen.getByTestId(
      "candidate-document-upload-input",
    ) as HTMLInputElement;
    fireEvent.change(input, {
      target: {
        files: [
          new File(["a"], "a.pdf", { type: "application/pdf" }),
          new File(["b"], "b.pdf", { type: "application/pdf" }),
        ],
      },
    });

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
    // Reset po wyborze — inaczej ponowny wybór tego samego pliku nie odpali
    // `onChange` i upload po nieudanej próbie byłby niemożliwy.
    expect(input.value).toBe("");
    await waitFor(() =>
      expect(vi.mocked(api.get).mock.calls.length).toBeGreaterThan(1),
    );
  });

  it("surfaces a failed upload instead of silently swallowing it", async () => {
    vi.mocked(api.post).mockRejectedValue(new Error("Plik za duży"));
    renderTab();
    await screen.findByRole("button", { name: /Dodaj plik/ });

    pickFile(new File(["x"], "duzy.pdf", { type: "application/pdf" }));

    await waitFor(() => expect(showError).toHaveBeenCalledWith("Plik za duży"));
    expect(showToast).not.toHaveBeenCalled();
    // Lista odświeża się też po błędzie — przy wielu plikach te wgrane przed
    // awarią są już w bazie i muszą być widoczne.
    await waitFor(() =>
      expect(vi.mocked(api.get).mock.calls.length).toBeGreaterThan(1),
    );
  });

  it("hides the uploader from roles without candidate write access", async () => {
    currentRole = "user";
    renderTab();

    expect(await screen.findByText("Brak plików.")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Dodaj plik/ }),
    ).not.toBeInTheDocument();
  });

  // Granica dwóch capability kandydackich przebiega DOKŁADNIE po HoR: teczkę
  // czyta (CandidateDocumentAccess), ale POST dokumentu to CandidateWriteAccess
  // bez niego. Ten przypadek był dotąd zielony przypadkiem — ręczna lista
  // gubiła HoR razem z finansami, więc nie pilnował właściwego guardu.
  it("HoR widzi listę plików, ale nie ma uploadera (CandidateWriteAccess bez HoR)", async () => {
    currentRole = "head_of_recruitment";
    renderTab();

    expect(await screen.findByText("Brak plików.")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Dodaj plik/ }),
    ).not.toBeInTheDocument();
  });

  // Odwrotna regresja: CANDIDATE_WRITE_ROLES zawiera `finance` (tier
  // recruitera od 19.08), więc backend odpowiada mu 200, a front chował
  // uploader. Ten przypadek jest CZERWONY przed zmianą.
  it("finance ma uploader (CANDIDATE_WRITE_ROLES zawiera finance)", async () => {
    currentRole = "finance";
    renderTab();

    expect(
      await screen.findByRole("button", { name: /Dodaj plik/ }),
    ).toBeInTheDocument();
  });
});
