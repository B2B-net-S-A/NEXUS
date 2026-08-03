import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { UserModal } from "./UserModal";

describe("UserModal — exclusive personas", () => {
  it("clears operational roles when Finance becomes primary", () => {
    const onSave = vi.fn();
    render(
      <UserModal
        initial={{
          role: "delivery_lead",
          roles: ["delivery_lead", "tac"],
        }}
        onClose={vi.fn()}
        onSave={onSave}
        loading={false}
      />,
    );

    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "finance" },
    });

    expect(screen.getByRole("checkbox", { name: /Finanse/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "TAC" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        role: "finance",
        roles: ["finance"],
        recruiter_role: "",
      }),
    );
  });

  it("removes Finance when switching back to an operational primary role", () => {
    const onSave = vi.fn();
    render(
      <UserModal
        initial={{ role: "finance", roles: ["finance"] }}
        onClose={vi.fn()}
        onSave={onSave}
        loading={false}
      />,
    );

    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "recruiter" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        role: "recruiter",
        roles: ["recruiter"],
      }),
    );
  });

  it("never offers Viewer as a secondary role and removes stale Viewer hybrids", () => {
    const onSave = vi.fn();
    render(
      <UserModal
        initial={{
          role: "recruiter",
          roles: ["recruiter", "user"],
        }}
        onClose={vi.fn()}
        onSave={onSave}
        loading={false}
      />,
    );

    expect(
      screen.queryByRole("checkbox", { name: /Viewer/ }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        role: "recruiter",
        roles: ["recruiter"],
      }),
    );
  });

  it("clears Viewer when switching to an operational primary role", () => {
    const onSave = vi.fn();
    render(
      <UserModal
        initial={{ role: "user", roles: ["user"] }}
        onClose={vi.fn()}
        onSave={onSave}
        loading={false}
      />,
    );

    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "delivery_lead" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        role: "delivery_lead",
        roles: ["delivery_lead"],
      }),
    );
  });
});
