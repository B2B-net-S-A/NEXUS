"use client";

// Ustawienia e-faktur Peppol: tryb (test/produkcja), automatyczna wysyłka
// i adresy odbiorców w sieci Peppol (plan Nordei N2). Tryb produkcyjny
// i automat wymagają potwierdzenia, bo e-faktury w systemie klienta nie da
// się wycofać.
import { useEffect, useState } from "react";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useEinvoiceSettings,
  useSaveEinvoiceSettings,
  type EinvoiceReceiver,
} from "@/lib/api/client-einvoices";
import { CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

export function EinvoiceSettingsPanel({ onClose }: { onClose: () => void }) {
  const query = useEinvoiceSettings();
  const save = useSaveEinvoiceSettings();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showSuccess, showError } = useToast();
  const [receivers, setReceivers] = useState<EinvoiceReceiver[]>([]);

  useEffect(() => {
    if (query.data) setReceivers(query.data.receivers);
  }, [query.data]);

  if (query.isError) {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(query.error, "Nie udało się pobrać ustawień e-faktur.")}
        onRetry={() => query.refetch()}
      />
    );
  }
  if (!query.isSuccess) return null;
  const data = query.data;

  async function apply(patch: Parameters<typeof save.mutateAsync>[0], done: string) {
    try {
      await save.mutateAsync(patch);
      showSuccess(done);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać ustawień."));
    }
  }

  async function onMode(production: boolean) {
    if (production) {
      const ok = await askConfirm({
        title: "Przełączyć na produkcję?",
        description:
          "Każda wysyłka trafi do systemu klienta (np. Visma Nordei), a tam e-faktury nie da się anulować. Przełącz dopiero po udanym teście na adres testowy.",
        confirmLabel: "Przełącz na produkcję",
        variant: "destructive",
      });
      if (!ok) return;
    }
    await apply({ mode: production ? "production" : "test" }, production ? "Tryb produkcyjny włączony." : "Tryb testowy włączony.");
  }

  async function onAuto(enabled: boolean) {
    if (enabled) {
      const ok = await askConfirm({
        title: "Włączyć wysyłkę automatyczną?",
        description: `Co godzinę, przy pobieraniu faktur z KSeF, NEXUS wyśle sam każdą e-fakturę „Do wysłania” (${data.mode === "test" ? "na adresy testowe" : "do systemów klientów"}).`,
        confirmLabel: "Włącz",
      });
      if (!ok) return;
    }
    await apply({ auto_send: enabled }, enabled ? "Wysyłka automatyczna włączona." : "Wysyłka automatyczna wyłączona.");
  }

  function edit(index: number, field: "peppol_id" | "test_peppol_id", value: string) {
    setReceivers((prev) => prev.map((r, i) => (i === index ? { ...r, [field]: value.trim() || null } : r)));
  }

  return (
    <section className="space-y-3 rounded-xl border bg-card p-3">
      {confirmDialog}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={data.mode === "production"} disabled={save.isPending} onCheckedChange={onMode} aria-label="Tryb produkcyjny" />
          Produkcja <span className="text-xs text-muted-foreground">(wyłączone = adres testowy odbiorcy)</span>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={data.auto_send} disabled={save.isPending} onCheckedChange={onAuto} aria-label="Wysyłka automatyczna" />
          Wysyłka automatyczna
        </label>
        <span className="text-xs text-muted-foreground">
          Dostawca: {data.provider === "off" ? "brak" : data.provider} · e-faktury od {data.since}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-[13px]">
          <thead className="border-b text-left">
            <tr>
              <th className={cn(CALM_HEAD, "py-1.5 pr-2")}>Odbiorca</th>
              <th className={cn(CALM_HEAD, "py-1.5 pr-2")}>VAT z faktury</th>
              <th className={cn(CALM_HEAD, "py-1.5 pr-2")}>Adres Peppol</th>
              <th className={cn(CALM_HEAD, "py-1.5")}>Adres testowy</th>
            </tr>
          </thead>
          <tbody>
            {receivers.map((r, index) => (
              <tr key={r.key} className={CALM_ROW}>
                <td className="py-1.5 pr-2">{r.name}</td>
                <td className="py-1.5 pr-2 font-mono text-xs">{r.key}</td>
                <td className="py-1.5 pr-2">
                  <Input
                    aria-label={`Adres Peppol: ${r.name}`}
                    value={r.peppol_id ?? ""}
                    placeholder="brak — faktury czekają"
                    onChange={(e) => edit(index, "peppol_id", e.target.value)}
                    className="h-7 font-mono text-xs"
                  />
                </td>
                <td className="py-1.5">
                  <Input
                    aria-label={`Adres testowy: ${r.name}`}
                    value={r.test_peppol_id ?? ""}
                    onChange={(e) => edit(index, "test_peppol_id", e.target.value)}
                    className="h-7 font-mono text-xs"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex justify-end gap-1.5">
        <Button size="sm" variant="ghost" onClick={onClose}>
          Zamknij
        </Button>
        <Button size="sm" disabled={save.isPending} onClick={() => apply({ receivers }, "Zapisano adresy odbiorców.")}>
          Zapisz adresy
        </Button>
      </div>
    </section>
  );
}
