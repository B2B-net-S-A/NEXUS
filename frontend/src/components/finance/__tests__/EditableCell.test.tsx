import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EditableCell } from "@/components/finance/EditableCell";

describe("EditableCell finance read access", () => {
  it("nie otwiera edycji w trybie tylko do odczytu", () => {
    const onSave = vi.fn();
    render(
      <table>
        <tbody>
          <tr>
            <EditableCell
              value={1250}
              display={<span>1 250 zł</span>}
              ariaLabel="Stawka"
              needsCompletion={false}
              onSave={onSave}
              onError={vi.fn()}
              readOnly
            />
          </tr>
        </tbody>
      </table>,
    );

    fireEvent.doubleClick(screen.getByText("1 250 zł"));

    expect(screen.queryByRole("textbox", { name: "Stawka" })).not.toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });
});
