"use client";

import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export interface SignedDeleteRequirement {
  contractorName: string | null;
}

export type SignedDeleteAction =
  | { kind: "confirm"; requirement: SignedDeleteRequirement }
  | { kind: "admin_required"; requirement: SignedDeleteRequirement };

export function signedDeleteRequirementFromError(
  error: unknown,
): SignedDeleteRequirement | null {
  if (!error || typeof error !== "object") return null;
  const response = (
    error as {
      response?: { status?: unknown; data?: { detail?: unknown } };
    }
  ).response;
  if (response?.status !== 409) return null;
  const detail = response.data?.detail;
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return null;
  const requirement = detail as {
    code?: unknown;
    requires_admin_confirmation?: unknown;
    contractor_name?: unknown;
  };
  if (
    requirement.code !== "contract_has_signed_generated_contract" ||
    requirement.requires_admin_confirmation !== true
  ) {
    return null;
  }
  return {
    contractorName:
      typeof requirement.contractor_name === "string"
        ? requirement.contractor_name
        : null,
  };
}

export function signedDeleteActionFromError(
  error: unknown,
  isAdmin: boolean,
): SignedDeleteAction | null {
  const requirement = signedDeleteRequirementFromError(error);
  if (!requirement) return null;
  return {
    kind: isAdmin ? "confirm" : "admin_required",
    requirement,
  };
}

function normalizeConfirmation(value: string): string {
  return value
    .normalize("NFKC")
    .trim()
    .replace(/\s+/g, " ")
    .toLocaleLowerCase("pl");
}

export function matchesSignedDeleteConfirmation(
  value: string,
  contractId: number,
  contractorName: string | null,
): boolean {
  const normalized = normalizeConfirmation(value);
  if (!normalized) return false;
  return (
    normalized === String(contractId) ||
    normalized === `#${contractId}` ||
    (!!contractorName && normalized === normalizeConfirmation(contractorName))
  );
}

interface SignedContractDeleteConfirmationProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  contractId: number;
  contractorName: string | null;
  isPending: boolean;
  error?: string;
  onConfirm: (confirmation: string) => void;
}

export function SignedContractDeleteConfirmation({
  open,
  onOpenChange,
  contractId,
  contractorName,
  isPending,
  error,
  onConfirm,
}: SignedContractDeleteConfirmationProps) {
  const [confirmation, setConfirmation] = useState("");

  useEffect(() => {
    if (open) setConfirmation("");
  }, [open, contractId]);

  const matches = matchesSignedDeleteConfirmation(
    confirmation,
    contractId,
    contractorName,
  );

  return (
    <AppModal
      open={open}
      onOpenChange={(next) => {
        if (!isPending) onOpenChange(next);
      }}
      title="Wymusić usunięcie podpisanego kontraktu?"
      description="Ta operacja jest dostępna wyłącznie dla administratora i zostanie odnotowana w audycie jako wymuszone usunięcie mimo podpisanej umowy."
      footer={
        <>
          <Button
            type="button"
            variant="outline"
            disabled={isPending}
            onClick={() => onOpenChange(false)}
          >
            Anuluj
          </Button>
          <Button
            type="button"
            variant="destructive"
            loading={isPending}
            disabled={!matches}
            onClick={() => onConfirm(confirmation.trim())}
          >
            <Trash2 className="h-4 w-4" />
            Usuń podpisany kontrakt
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="rounded-lg border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          Kontrakt #{contractId} ma umowę B2B potwierdzoną jako podpisana przez
          obie strony. Usunięcie jest nieodwracalne.
        </div>
        <div>
          <Label htmlFor="signed-contract-delete-confirmation" className="mb-1.5 block">
            Wpisz {contractorName ? `„${contractorName}” albo ` : ""}numer kontraktu
            „{contractId}”
          </Label>
          <Input
            id="signed-contract-delete-confirmation"
            autoComplete="off"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            placeholder={contractorName ?? String(contractId)}
            aria-invalid={confirmation.length > 0 && !matches}
          />
          {confirmation.length > 0 && !matches ? (
            <p className="mt-1 text-xs text-destructive">
              Wpisana wartość nie odpowiada nazwie kontraktora ani numerowi
              kontraktu.
            </p>
          ) : (
            <p className="mt-1 text-xs text-muted-foreground">
              Przycisk usunięcia uaktywni się dopiero po zgodnym wpisaniu.
            </p>
          )}
        </div>
        {error ? (
          <div className="rounded-lg bg-destructive/10 px-4 py-2 text-sm text-destructive">
            {error}
          </div>
        ) : null}
      </div>
    </AppModal>
  );
}
