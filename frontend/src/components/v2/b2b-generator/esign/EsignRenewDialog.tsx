"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarPlus, Check, Copy, Loader2, RefreshCw } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiErrorMessage } from "@/lib/api-error";
import type { B2BGeneratedContractRow } from "@/lib/api";
import { b2bEsignApi, type EsignSendResult } from "@/lib/api/b2bEsign";

export type EsignRenewMode = "extend" | "relink";

const COPY: Record<EsignRenewMode, { title: string; text: string; action: string }> = {
  extend: {
    title: "Przedłuż termin",
    text: "Link z pierwszego maila zadziała dłużej, umowa (PDF) się nie zmienia. Kontraktor dostanie krótki mail z nową datą.",
    action: "Przedłuż termin",
  },
  relink: {
    title: "Wyślij nowy link",
    text: "Kontraktor dostanie nowy link do tej samej umowy. PDF się nie zmienia, więc plik, który zdążył podpisać, nowy link przyjmie bez ponownego podpisu.",
    action: "Wyślij nowy link",
  },
};

/**
 * Wygasły albo wygasający link do podpisu (27.10.2026, pytanie zespołu „co
 * jeśli link wygaśnie?”): oba warianty zostają na zamrożonym PDF-ie.
 */
export function EsignRenewDialog({
  row,
  mode,
  onClose,
}: {
  row: B2BGeneratedContractRow;
  mode: EsignRenewMode;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  // Te same terminy co przy wysyłce (Sandra, 26.10.2026).
  const [days, setDays] = useState(3);
  const [result, setResult] = useState<EsignSendResult | null>(null);
  const [extendedTo, setExtendedTo] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const requestId = row.esign?.request_id ?? 0;
  const copy = COPY[mode];

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
    queryClient.invalidateQueries({ queryKey: ["kanban"] });
    queryClient.invalidateQueries({ queryKey: ["board-tasks"] });
  };
  const renew = useMutation({
    mutationFn: async () => {
      if (mode === "relink") {
        setResult(await b2bEsignApi.relink(requestId, days));
      } else {
        const updated = await b2bEsignApi.extend(requestId, days);
        setExtendedTo(updated.expires_at);
      }
    },
    onSuccess: refresh,
  });

  const done = result !== null || extendedTo !== null;
  const day = (value: string) =>
    new Date(value).toLocaleDateString("pl-PL", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      timeZone: "Europe/Warsaw",
    });
  const copyLink = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.sign_url);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => (!open && !renew.isPending ? onClose() : undefined)}>
      <DialogContent size="md">
        <DialogHeader>
          <DialogTitle>
            {copy.title}: umowa {row.contract_number}
          </DialogTitle>
          <DialogDescription>
            {[row.partner_display_name ?? row.partner_name, row.canonical_client_name]
              .filter(Boolean)
              .join(" · ")}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          {extendedTo ? (
            <Alert
              variant="success"
              title={`Termin przedłużony do ${day(extendedTo)}`}
              description="Link z pierwszego maila działa dalej. Kontraktor dostał mail z nową datą, jeśli Twoja skrzynka jest połączona."
            />
          ) : result ? (
            <div className="space-y-3">
              <Alert
                variant={result.mail_sent ? "success" : "warning"}
                title={
                  result.mail_sent
                    ? `Nowy link wysłany do ${result.request.contractor_email ?? "kontraktora"}`
                    : "Nowy link gotowy: wyślij go kontraktorowi"
                }
                description={
                  result.mail_sent
                    ? `Link działa do ${day(result.request.expires_at)}.`
                    : (result.mail_problem ?? "Skopiuj link i wyślij go kontraktorowi.")
                }
              />
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  readOnly
                  value={result.sign_url}
                  aria-label="Nowy link do podpisu"
                  className="min-w-0 flex-1"
                />
                <Button type="button" variant="outline" onClick={() => void copyLink()}>
                  {copied ? <Check className="h-4 w-4" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />}
                  {copied ? "Skopiowano" : "Kopiuj link"}
                </Button>
              </div>
            </div>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">{copy.text}</p>
              <div className="max-w-[200px] space-y-1">
                <Label htmlFor={`esign-renew-days-${row.id}`}>
                  {mode === "extend" ? "O ile dni" : "Termin na podpis"}
                </Label>
                <select
                  id={`esign-renew-days-${row.id}`}
                  className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                  value={days}
                  onChange={(e) => setDays(Number(e.target.value))}
                >
                  <option value={1}>1 dzień</option>
                  <option value={3}>3 dni</option>
                  <option value={5}>5 dni</option>
                  <option value={7}>7 dni</option>
                </select>
              </div>
              {renew.isError ? (
                <Alert
                  variant="error"
                  title={mode === "extend" ? "Nie udało się przedłużyć" : "Nie udało się wysłać"}
                  description={apiErrorMessage(renew.error, "Spróbuj ponownie.")}
                />
              ) : null}
            </>
          )}
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose} disabled={renew.isPending}>
            {done ? "Zamknij" : "Anuluj"}
          </Button>
          {!done ? (
            <Button
              type="button"
              variant="primary"
              disabled={renew.isPending || !requestId}
              onClick={() => renew.mutate()}
            >
              {renew.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : mode === "extend" ? (
                <CalendarPlus className="h-4 w-4" aria-hidden />
              ) : (
                <RefreshCw className="h-4 w-4" aria-hidden />
              )}
              {copy.action}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
