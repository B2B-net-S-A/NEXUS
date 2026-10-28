import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  toast: vi.fn(),
  confirm: vi.fn(async () => true),
}));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: mocks.post } }));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.toast }),
}));

vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: mocks.confirm, confirmDialog: null }),
}));

import { MoveToAccountDialog } from "../MoveToAccountDialog";

// Dane fikcyjne — repo jest publiczne.
const PERSON = {
  kind: "external" as const,
  id: 41,
  name: "Karolina Przykładowa",
  email: null,
  detail: "Osoba spoza NEXUSA",
};
const ACCOUNT = {
  kind: "user" as const,
  id: 77,
  name: "Karolina Przykładowa",
  email: "karolina@example.com",
  detail: "Konto NEXUSA",
};

function renderDialog(onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MoveToAccountDialog person={PERSON} onClose={onClose} />
    </QueryClientProvider>,
  );
  return onClose;
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.confirm.mockResolvedValue(true);
  mocks.get.mockImplementation(async (url: string) =>
    url.startsWith("/api/equipment/holders/external/")
      ? { data: { holder: PERSON, active: [{ assignment_id: 1 }, { assignment_id: 2 }], history: [] } }
      : { data: { items: [ACCOUNT] } },
  );
});

async function chooseAccount() {
  const user = userEvent.setup();
  await user.type(screen.getByRole("textbox", { name: "Szukaj konta NEXUSA" }), "Karo");
  await user.click(await screen.findByRole("button", { name: /Karolina Przykładowa/ }));
  return user;
}

describe("MoveToAccountDialog", () => {
  it("asks for confirmation and moves the equipment to the chosen account", async () => {
    mocks.post.mockResolvedValue({
      data: { holder: ACCOUNT, assignments: 2, protocols: 1, confirmed_protocols: 1, tasks: 1 },
    });
    const onClose = renderDialog();
    expect(await screen.findByText(/Do przepisania: 2 rzeczy/)).toBeInTheDocument();
    const user = await chooseAccount();
    await user.click(screen.getByRole("button", { name: "Przepisz na konto" }));
    expect(mocks.confirm).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Przepisać sprzęt na konto Karolina Przykładowa?" }),
    );
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/equipment/external-people/41/move-to-user", {
        user_id: 77,
      }),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(mocks.toast).toHaveBeenCalledWith(
      "Przepisano na konto Karolina Przykładowa: 2 rzeczy",
      "success",
    );
  });

  it("does nothing when the confirmation is declined", async () => {
    mocks.confirm.mockResolvedValue(false);
    renderDialog();
    const user = await chooseAccount();
    await user.click(screen.getByRole("button", { name: "Przepisz na konto" }));
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("shows the server refusal in Polish and stays open", async () => {
    mocks.post.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 409,
        data: { detail: "Konto Karolina Przykładowa jest nieaktywne — sprzęt przepiszesz tylko na aktywne konto NEXUSA." },
      },
    });
    const onClose = renderDialog();
    const user = await chooseAccount();
    await user.click(screen.getByRole("button", { name: "Przepisz na konto" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/jest nieaktywne/);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("cannot move before an account is chosen", () => {
    renderDialog();
    expect(screen.getByRole("button", { name: "Przepisz na konto" })).toBeDisabled();
  });
});
