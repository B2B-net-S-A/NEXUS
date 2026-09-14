import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { UserModal } from "./UserModal";

describe("UserModal — exclusive personas", () => {
  it("offers Talent Community Manager as a provisionable role", () => {
    render(
      <UserModal
        initial={{ role: "recruiter", roles: ["recruiter"] }}
        onClose={vi.fn()}
        onSave={vi.fn()}
        loading={false}
      />,
    );

    expect(
      screen.getByRole("option", { name: "Talent Community Manager" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Talent Community Manager" }),
    ).toBeInTheDocument();
  });

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
    expect(
      screen.queryByRole("option", { name: /Viewer/ }),
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

describe("UserModal — imienne uprawnienie do usuwania klientów", () => {
  it("pozwala nadać uprawnienie przy edycji konta", () => {
    const onSave = vi.fn();
    render(
      <UserModal
        initial={{ id: 5, role: "finance", roles: ["finance"], can_delete_clients: false }}
        onClose={vi.fn()}
        onSave={onSave}
        loading={false}
      />,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: "Może usuwać klientów" }));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ can_delete_clients: true }),
    );
  });

  it("nie pokazuje uprawnienia przy zakładaniu konta", () => {
    render(
      <UserModal initial={null} onClose={vi.fn()} onSave={vi.fn()} loading={false} />,
    );

    expect(
      screen.queryByRole("checkbox", { name: "Może usuwać klientów" }),
    ).not.toBeInTheDocument();
  });

  it("pokazuje odmowę serwera zamiast milczeć (UAT M11-B10)", () => {
    render(
      <UserModal
        initial={null}
        onClose={vi.fn()}
        onSave={vi.fn()}
        loading={false}
        error="Adres e-mail musi być w domenie firmy (firma.example)."
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/domenie firmy/);
  });
});
