import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { useConfirmV2 } from "../ConfirmV2";

function Harness({ onAction }: { onAction: () => void }) {
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [answer, setAnswer] = useState<string>("—");
  return (
    <div>
      {confirmDialog}
      <button
        type="button"
        onClick={async () => {
          const ok = await askConfirm({
            title: 'Usunąć szablon "Oferta"?',
            description: "Tej akcji nie można cofnąć.",
            confirmLabel: "Usuń",
            variant: "destructive",
          });
          setAnswer(ok ? "tak" : "nie");
          if (ok) onAction();
        }}
      >
        Usuń szablon
      </button>
      <output>{answer}</output>
    </div>
  );
}

describe("useConfirmV2 — zamiennik window.confirm", () => {
  it("pokazuje pytanie w oknie aplikacji, bez natywnego confirm", async () => {
    const native = vi.spyOn(window, "confirm");
    const user = userEvent.setup();
    render(<Harness onAction={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Usuń szablon" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent('Usunąć szablon "Oferta"?');
    expect(dialog).toHaveTextContent("Tej akcji nie można cofnąć.");
    expect(native).not.toHaveBeenCalled();
    native.mockRestore();
  });

  it("Anuluj = nic się nie dzieje", async () => {
    const onAction = vi.fn();
    const user = userEvent.setup();
    render(<Harness onAction={onAction} />);

    await user.click(screen.getByRole("button", { name: "Usuń szablon" }));
    await user.click(await screen.findByRole("button", { name: "Anuluj" }));

    await waitFor(() => expect(screen.getByText("nie")).toBeInTheDocument());
    expect(onAction).not.toHaveBeenCalled();
  });

  it("Esc = anulowanie", async () => {
    const onAction = vi.fn();
    const user = userEvent.setup();
    render(<Harness onAction={onAction} />);

    await user.click(screen.getByRole("button", { name: "Usuń szablon" }));
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.getByText("nie")).toBeInTheDocument());
    expect(onAction).not.toHaveBeenCalled();
  });

  it("podwójne kliknięcie w potwierdzenie wykonuje akcję raz", async () => {
    const onAction = vi.fn();
    const user = userEvent.setup();
    render(<Harness onAction={onAction} />);

    await user.click(screen.getByRole("button", { name: "Usuń szablon" }));
    const confirmButton = await screen.findByRole("button", { name: "Usuń" });
    await user.dblClick(confirmButton);

    await waitFor(() => expect(screen.getByText("tak")).toBeInTheDocument());
    expect(onAction).toHaveBeenCalledTimes(1);
  });
});
