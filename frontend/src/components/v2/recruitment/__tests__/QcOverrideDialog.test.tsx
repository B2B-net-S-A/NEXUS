import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { post: (...a: unknown[]) => post(...a) },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError }),
}));

import { QcOverrideDialog, overrideSummary } from "@/components/v2/recruitment/QcOverrideDialog";

const OVERRIDE_URL = "/api/pipeline/stages/7/qc/override";

function renderDialog(pending = ["Hibernate — brak opisu w 3 rolach", "REST API — jest w CV, a nie ma tego w oryginale"]) {
  const onOpenChange = vi.fn();
  const onChanged = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <QcOverrideDialog stageId={7} open onOpenChange={onOpenChange} pending={pending} onChanged={onChanged} />
    </QueryClientProvider>,
  );
  return { onOpenChange, onChanged };
}

describe("QcOverrideDialog — „Przepuść mimo QC”", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    post.mockResolvedValue({ data: { stage_id: 7, job_id: 31 } });
  });

  it("mówi, z czym CV pójdzie dalej", () => {
    renderDialog();
    const dialog = screen.getByRole("dialog", { name: "Przepuść mimo QC" });
    expect(dialog).toHaveTextContent("CV pójdzie dalej z 2 niepoprawionymi rzeczami:");
    expect(dialog).toHaveTextContent("Hibernate — brak opisu w 3 rolach");
    expect(dialog).toHaveTextContent("Powód zobaczy każdy w historii kandydata.");
    expect(overrideSummary(1)).toBe("CV pójdzie dalej z 1 niepoprawioną rzeczą:");
  });

  it("długa lista jest skracana do czterech pozycji", () => {
    renderDialog(["a", "b", "c", "d", "e", "f"]);
    const items = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toEqual(["a", "b", "c", "d", "i 2 inne"]);
  });

  it("bez wybranego powodu nic nie wysyła", async () => {
    renderDialog();
    await userEvent.click(screen.getByRole("button", { name: "Przepuść CV" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Wybierz powód.");
    expect(post).not.toHaveBeenCalled();
  });

  it("gotowy powód wystarcza — opis jest opcjonalny i nie ma minimum znaków", async () => {
    const { onOpenChange, onChanged } = renderDialog();
    await userEvent.click(screen.getByRole("radio", { name: "To wymaganie nie dotyczy tej roli" }));
    expect(screen.getByLabelText("Szczegóły (nie musisz nic wpisywać)")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Przepuść CV" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(OVERRIDE_URL, { reason_code: "requirement_not_applicable" }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(onChanged).toHaveBeenCalled();
    expect(showSuccess).toHaveBeenCalledWith("Przepuszczono mimo QC — powód zapisany w historii.");
  });

  it("opis dopisany do gotowego powodu jedzie razem z nim", async () => {
    renderDialog();
    await userEvent.click(screen.getByRole("radio", { name: "Klient prosił o krótsze CV" }));
    await userEvent.type(screen.getByRole("textbox"), "  2 strony ");
    await userEvent.click(screen.getByRole("button", { name: "Przepuść CV" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(OVERRIDE_URL, { reason_code: "client_short_cv", reason: "2 strony" }),
    );
  });

  it("„Inny powód” wymaga opisu — choćby jednego słowa", async () => {
    renderDialog();
    await userEvent.click(screen.getByRole("radio", { name: "Inny powód — napiszę niżej" }));
    await userEvent.click(screen.getByRole("button", { name: "Przepuść CV" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Przy „Inny powód” napisz, dlaczego przepuszczasz.");
    expect(post).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText("Szczegóły (wymagane)"), "pilne");
    await userEvent.click(screen.getByRole("button", { name: "Przepuść CV" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(OVERRIDE_URL, { reason_code: "other", reason: "pilne" }));
  });

  it("odmowa serwera zostawia okno otwarte z komunikatem", async () => {
    post.mockRejectedValue({ response: { status: 403, data: { detail: "QC może obejść tylko Delivery Lead albo admin." } } });
    const { onOpenChange } = renderDialog();
    await userEvent.click(screen.getByRole("radio", { name: "Klient prosił o krótsze CV" }));
    await userEvent.click(screen.getByRole("button", { name: "Przepuść CV" }));
    await waitFor(() => expect(showError).toHaveBeenCalledWith("QC może obejść tylko Delivery Lead albo admin."));
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });
});
