import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CopyValueButton } from "@/components/clients/CopyValueButton";

const showSuccess = vi.fn();
const showError = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError }),
}));

const copyText = vi.fn();
vi.mock("@/lib/clipboard", () => ({
  copyTextToClipboard: (text: string) => copyText(text),
}));

describe("CopyValueButton", () => {
  beforeEach(() => {
    showSuccess.mockReset();
    showError.mockReset();
    copyText.mockReset();
  });

  it("kopiuje wartość i mówi, co skopiowano", async () => {
    copyText.mockResolvedValue(true);
    render(<CopyValueButton value="anna@example.com" what="adres e-mail" />);
    fireEvent.click(screen.getByRole("button", { name: "Kopiuj adres e-mail" }));
    await waitFor(() => expect(showSuccess).toHaveBeenCalledWith("Skopiowano adres e-mail"));
    expect(copyText).toHaveBeenCalledWith("anna@example.com");
    expect(showError).not.toHaveBeenCalled();
  });

  it("nie udaje sukcesu, gdy schowek odmówił", async () => {
    copyText.mockResolvedValue(false);
    render(<CopyValueButton value="600 833 277" what="numer telefonu" />);
    fireEvent.click(screen.getByRole("button", { name: "Kopiuj numer telefonu" }));
    await waitFor(() =>
      expect(showError).toHaveBeenCalledWith(
        "Nie udało się skopiować — zaznacz numer telefonu i skopiuj ręcznie.",
      ),
    );
    expect(showSuccess).not.toHaveBeenCalled();
  });
});
