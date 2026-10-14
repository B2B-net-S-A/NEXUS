import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SecretRevealCard } from "./SecretRevealCard";

function renderCard() {
  const onClose = vi.fn();
  render(
    <SecretRevealCard
      title="Zapisz teraz klucz „n8n”"
      description="Klucz widać tylko teraz."
      secret="nxs_v2_000000000000000000000009_PODGLAD-test"
      onClose={onClose}
    >
      <p>Nagłówek X-API-Key</p>
    </SecretRevealCard>,
  );
  return { onClose, user: userEvent.setup() };
}

describe("SecretRevealCard — sekret pokazywany raz", () => {
  afterEach(() => vi.restoreAllMocks());

  it("pokazuje sekret i dodatkową treść, kopiuje do schowka", async () => {
    const { user } = renderCard();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
    expect(screen.getByTestId("revealed-secret")).toHaveTextContent(
      "nxs_v2_000000000000000000000009_PODGLAD-test",
    );
    expect(screen.getByText("Nagłówek X-API-Key")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Skopiuj" }));
    expect(writeText).toHaveBeenCalledWith("nxs_v2_000000000000000000000009_PODGLAD-test");
    expect(await screen.findByRole("button", { name: "Skopiowano" })).toBeInTheDocument();
  });

  it("niedostępny schowek nie chowa sekretu, tylko mówi, żeby skopiować ręcznie", async () => {
    const { user } = renderCard();
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("denied"));
    await user.click(screen.getByRole("button", { name: "Skopiuj" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("skopiuj go ręcznie");
    expect(screen.getByTestId("revealed-secret")).toBeInTheDocument();
  });

  it("zamyka się tylko przyciskiem „Zamknij”", async () => {
    const { onClose, user } = renderCard();
    await user.click(screen.getByRole("button", { name: "Zamknij" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
