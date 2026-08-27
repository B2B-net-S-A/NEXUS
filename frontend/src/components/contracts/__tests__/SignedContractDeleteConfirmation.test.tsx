import * as React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/ds/AppModal", () => ({
  AppModal: ({
    open,
    title,
    description,
    footer,
    children,
  }: {
    open: boolean;
    title: string;
    description?: string;
    footer?: React.ReactNode;
    children: React.ReactNode;
  }) =>
    open ? (
      <section aria-label={title}>
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
        {children}
        {footer}
      </section>
    ) : null,
}));

import {
  SignedContractDeleteConfirmation,
  matchesSignedDeleteConfirmation,
  signedDeleteActionFromError,
  signedDeleteRequirementFromError,
} from "@/components/contracts/SignedContractDeleteConfirmation";

describe("signed contract forced delete confirmation", () => {
  it("recognises only the structured signed-contract 409", () => {
    const signedError = {
      response: {
        status: 409,
        data: {
          detail: {
            code: "contract_has_signed_generated_contract",
            requires_admin_confirmation: true,
            contractor_name: "Agnieszka Urbaniak",
          },
        },
      },
    };
    expect(signedDeleteRequirementFromError(signedError)).toEqual({
      contractorName: "Agnieszka Urbaniak",
    });
    expect(signedDeleteActionFromError(signedError, true)).toMatchObject({
      kind: "confirm",
    });
    expect(signedDeleteActionFromError(signedError, false)).toMatchObject({
      kind: "admin_required",
    });
    expect(
      signedDeleteRequirementFromError({
        response: { status: 409, data: { detail: "Conflict" } },
      }),
    ).toBeNull();
  });

  it("accepts the full contractor name or contract number, but not a fragment", () => {
    expect(
      matchesSignedDeleteConfirmation(
        "  agnieszka   URBANIAK ",
        563,
        "Agnieszka Urbaniak",
      ),
    ).toBe(true);
    expect(matchesSignedDeleteConfirmation("563", 563, "Agnieszka Urbaniak")).toBe(
      true,
    );
    expect(
      matchesSignedDeleteConfirmation("Agnieszka", 563, "Agnieszka Urbaniak"),
    ).toBe(false);
  });

  it("keeps the final destructive action disabled until the input matches", async () => {
    const user = userEvent.setup({ delay: null });
    const onConfirm = vi.fn();
    render(
      <SignedContractDeleteConfirmation
        open
        onOpenChange={vi.fn()}
        contractId={563}
        contractorName="Agnieszka Urbaniak"
        isPending={false}
        onConfirm={onConfirm}
      />,
    );

    const button = screen.getByRole("button", {
      name: /Usuń podpisany kontrakt/i,
    });
    const input = screen.getByLabelText(/Wpisz.*Agnieszka Urbaniak.*563/i);
    expect(button).toBeDisabled();

    await user.type(input, "Agnieszka");
    expect(button).toBeDisabled();
    expect(screen.getByText(/nie odpowiada nazwie kontraktora/i)).toBeInTheDocument();

    await user.clear(input);
    await user.type(input, "563");
    expect(button).toBeEnabled();
    await user.click(button);
    expect(onConfirm).toHaveBeenCalledWith("563");
  });
});
