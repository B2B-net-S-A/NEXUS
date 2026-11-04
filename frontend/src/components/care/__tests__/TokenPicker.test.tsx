import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TokenPicker, type PickedToken } from "../TokenPicker";

function Harness({
  search,
  onChange,
}: {
  search: (q: string) => Promise<{ id: number; name: string }[]>;
  onChange: (next: PickedToken[]) => void;
}) {
  const [value, setValue] = useState<PickedToken[]>([]);
  return (
    <TokenPicker
      label="Technologie"
      value={value}
      search={search}
      freeTextHint="do przejrzenia"
      onChange={(next) => {
        setValue(next);
        onChange(next);
      }}
    />
  );
}

describe("TokenPicker — nazwa spoza słownika", () => {
  it("pokazuje „Dodaj …”, gdy słownik nie zna nazwy, i dodaje ją po kliknięciu", async () => {
    const onChange = vi.fn();
    render(<Harness search={async () => [{ id: 1, name: "python" }]} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Technologie"), { target: { value: "Pulumix" } });

    const add = await screen.findByRole("button", { name: /Dodaj „Pulumix”/ });
    fireEvent.click(add);

    expect(onChange).toHaveBeenLastCalledWith([{ id: null, name: "Pulumix" }]);
  });

  it("przy dokładnym trafieniu w słowniku nie proponuje nazwy tekstem", async () => {
    render(<Harness search={async () => [{ id: 7, name: "Python" }]} onChange={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Technologie"), { target: { value: "python" } });

    await screen.findByRole("button", { name: "Python" });
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /Dodaj „/ })).not.toBeInTheDocument(),
    );
  });
});
