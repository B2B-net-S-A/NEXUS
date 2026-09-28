"use client";

import * as React from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  registryName,
  type CompanyVerification,
  type RegistryDiff,
} from "@/lib/b2b-registry-check";

/**
 * Wynik sprawdzenia firmy w CEIDG/KRS przed wygenerowaniem umowy (ticket 6).
 *
 * Wyłącznie informacja: „Generuj umowę” jest zawsze dostępne — ostrzeżenie
 * o zawieszeniu, likwidacji czy upadłości ani niedostępny rejestr nie blokują
 * dokumentu.
 */
export function RegistryCheckDialog({
  verification,
  diffs,
  applyRegistry,
  onApplyRegistryChange,
  onConfirm,
  onCancel,
}: {
  verification: CompanyVerification | null;
  diffs: RegistryDiff[];
  applyRegistry: boolean;
  onApplyRegistryChange: (value: boolean) => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const applyId = React.useId();
  const warnings = verification?.warnings ?? [];
  const unverified = verification?.status === "unverified";
  const registry = registryName(verification?.registry ?? null);

  const title =
    warnings.length > 0
      ? "Sprawdź status firmy Partnera"
      : unverified
        ? "Dane firmy nie zostały zweryfikowane"
        : `Dane firmy w ${registry} różnią się od formularza`;

  return (
    <Dialog
      open={verification !== null}
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
    >
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {unverified
              ? "Nie udało się sprawdzić firmy w rejestrze. Możesz wygenerować umowę, ale dane Partnera sprawdź ręcznie."
              : `Sprawdzono w ${registry} przed wygenerowaniem umowy. To tylko informacja — możesz wygenerować umowę.`}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3">
          {warnings.length > 0 ? (
            <Alert variant="error" title={`Ostrzeżenie z ${registry}`}>
              {/* Dzieci, nie `description`: ten renderuje się w <p>, a lista
                  w akapicie to niepoprawny HTML (błąd hydratacji). */}
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                {warnings.map((w) => (
                  <li key={w.code}>{w.message}</li>
                ))}
              </ul>
            </Alert>
          ) : null}
          {unverified ? (
            <Alert
              variant="warning"
              title="Dane firmy nie zostały zweryfikowane w rejestrze"
              description={verification?.message ?? undefined}
            />
          ) : null}
          {diffs.length > 0 ? (
            <div className="space-y-2">
              <p className="text-sm font-medium">
                Aktualne dane w {registry} różnią się od formularza:
              </p>
              <div className="rounded-lg border">
                <table className="w-full table-fixed text-sm break-words">
                  <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="w-[26%] px-2 py-2 font-medium sm:px-3">Pole</th>
                      <th className="px-2 py-2 font-medium sm:px-3">W formularzu</th>
                      <th className="px-2 py-2 font-medium sm:px-3">W {registry}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {diffs.map((d) => (
                      <tr key={d.field} className="border-t align-top">
                        <td className="px-2 py-2 text-xs text-muted-foreground sm:px-3 sm:text-sm">{d.label}</td>
                        <td className="px-2 py-2 sm:px-3">{d.form || "—"}</td>
                        <td className="px-2 py-2 sm:px-3 font-medium">{d.registry}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex items-start gap-2">
                <Checkbox
                  id={applyId}
                  checked={applyRegistry}
                  onCheckedChange={(v) => onApplyRegistryChange(v === true)}
                />
                <label htmlFor={applyId} className="text-sm leading-tight">
                  Wstaw do umowy aktualne dane z {registry}
                </label>
              </div>
            </div>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            Anuluj
          </Button>
          <Button onClick={onConfirm}>
            {warnings.length > 0 || unverified ? "Generuj mimo to" : "Generuj umowę"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
