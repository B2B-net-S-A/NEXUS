"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  downloadSignedProtocol,
  useConfirmProtocol,
  useCreateProtocolLink,
  useProtocol,
  useUploadSignedProtocol,
} from "@/lib/api/equipment";
import { resolveViewState } from "@/lib/view-state";
import { formatIsoDatePl } from "@/lib/date-pl";

import {
  CONDITION_LABELS,
  PROTOCOL_STATUS_LABELS,
  PROTOCOL_STATUS_TONE,
  SIGNATURE_LABELS,
  formatPln,
} from "./equipment-format";
import { ProtocolCorrectionDialog } from "./ProtocolCorrectionDialog";
import { ProtocolDownloads } from "./ProtocolDownloads";
import { ProtocolLinkBox } from "./ProtocolLinkBox";
import { useProtocolQuickActions } from "./useProtocolQuickActions";

type PaperMethod = "papier" | "profil_zaufany";

/**
 * Protokół: pozycje, link do podpisu, skan podpisanego pliku i potwierdzenie przez człowieka.
 * Przed podpisem „Popraw” (z anulowaniem w stopce), podpisany — „Anuluj protokół…”
 * (decyzja 28.10.2026). `startCorrecting` otwiera poprawkę od razu (⋯ na liście).
 */
export function ProtocolDialog({
  protocolId,
  onClose,
  startCorrecting = false,
}: {
  protocolId: number;
  onClose: () => void;
  startCorrecting?: boolean;
}) {
  const { showToast } = useToast();
  const detail = useProtocol(protocolId);
  const link = useCreateProtocolLink();
  const upload = useUploadSignedProtocol();
  const confirm = useConfirmProtocol();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const quick = useProtocolQuickActions();
  const [correcting, setCorrecting] = useState(startCorrecting);
  const [linkUrl, setLinkUrl] = useState<string | null>(null);
  const [method, setMethod] = useState<PaperMethod>("papier");
  const [error, setError] = useState<string | null>(null);
  const state = resolveViewState({
    isLoading: detail.isLoading,
    error: detail.error,
    isSuccess: detail.isSuccess,
  });
  const protocol = detail.data;
  const open = protocol && (protocol.status === "oczekuje" || protocol.status === "podpisany");

  const fail = (fallback: string) => (err: unknown) => setError(apiErrorMessage(err, fallback));

  const newLink = async () => {
    if (!protocol) return;
    if (protocol.link && !protocol.link.used_at) {
      const ok = await askConfirm({
        title: "Utworzyć nowy link?",
        description: "Poprzedni link do tego protokołu przestanie działać.",
        confirmLabel: "Utwórz nowy",
      });
      if (!ok) return;
    }
    setError(null);
    link.mutate(protocol.id, {
      onSuccess: (data) => setLinkUrl(data.url),
      onError: fail("Nie udało się utworzyć linku."),
    });
  };

  const onFile = (file: File | null) => {
    if (!file || !protocol) return;
    setError(null);
    upload.mutate(
      { protocolId: protocol.id, file, method },
      {
        onSuccess: () => showToast("Podpisany plik wgrany", "success"),
        onError: fail("Nie udało się wgrać pliku."),
      },
    );
  };

  const onConfirm = () => {
    if (!protocol) return;
    setError(null);
    confirm.mutate(
      {
        protocolId: protocol.id,
        ...(protocol.status === "oczekuje" ? { method } : {}),
      },
      {
        onSuccess: () => showToast("Podpis potwierdzony", "success"),
        onError: fail("Nie udało się potwierdzić podpisu."),
      },
    );
  };

  const afterCorrection = ({ linkRevoked }: { linkRevoked: boolean }) => {
    setCorrecting(false);
    showToast("Poprawki zapisane", "success");
    if (!protocol || !linkRevoked) return;
    // Stary link przestał działać — nowy od razu, recepcja wysyła go ponownie.
    link.mutate(protocol.id, {
      onSuccess: (data) => setLinkUrl(data.url),
      onError: fail("Poprawki zapisane, ale nowego linku nie udało się utworzyć."),
    });
  };

  const cancelThis = () => {
    if (!protocol) return;
    void quick.cancelProtocol(protocol, () => {
      setCorrecting(false);
      setLinkUrl(null);
    });
  };

  const downloadSigned = async () => {
    if (!protocol) return;
    try {
      await downloadSignedProtocol(protocol);
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się pobrać pliku."));
    }
  };

  return (
    <AppModal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={protocol ? `Protokół ${protocol.number}` : "Protokół"}
      description={
        protocol
          ? `${protocol.kind === "wydanie" ? "Wydanie" : "Zwrot"} · ${formatIsoDatePl(protocol.protocol_date)} · ${protocol.holder.name}`
          : undefined
      }
      size="lg"
      footer={
        <>
          {protocol?.status === "podpisany" ? (
            <Button
              variant="ghost"
              className="text-destructive hover:bg-destructive/10 sm:mr-auto"
              onClick={cancelThis}
              disabled={quick.busy}
            >
              Anuluj protokół…
            </Button>
          ) : null}
          <Button onClick={onClose}>Zamknij</Button>
        </>
      }
    >
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : state !== "ready" || !protocol ? (
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          onRetry={() => detail.refetch()}
        />
      ) : (
        <div className="space-y-4 text-sm">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
            <StatusDot tone={PROTOCOL_STATUS_TONE[protocol.status]}>
              {PROTOCOL_STATUS_LABELS[protocol.status]}
            </StatusDot>
            <span className="text-xs text-muted-foreground">
              Podpis: {SIGNATURE_LABELS[protocol.signature_method]}
              {protocol.signer_name ? ` · ${protocol.signer_name}` : ""}
              {protocol.signed_at ? ` · ${formatIsoDatePl(protocol.signed_at)}` : ""}
            </span>
            <span className="text-xs text-muted-foreground">Wydał(a): {protocol.issuer_name}</span>
            {protocol.status === "oczekuje" ? (
              <Button
                variant="outline"
                size="sm"
                className="ml-auto"
                onClick={() => setCorrecting(true)}
              >
                Popraw
              </Button>
            ) : null}
          </div>
          {protocol.status === "anulowany" && protocol.cancel_reason ? (
            <p className="text-xs text-muted-foreground">
              Anulowany
              {protocol.cancelled_at ? ` ${formatIsoDatePl(protocol.cancelled_at)}` : ""}: {protocol.cancel_reason}
            </p>
          ) : null}
          <table className="w-full text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr>
                <th className="py-1 text-left">Lp.</th>
                <th className="py-1 text-left">Nazwa sprzętu</th>
                <th className="py-1 text-left">Nr seryjny</th>
                <th className="py-1 text-right">
                  {protocol.kind === "wydanie" ? "Wartość" : "Stan"}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {(protocol.lines ?? []).map((line) => (
                <tr key={line.position}>
                  <td className="py-1">{line.position}</td>
                  <td className="py-1">{line.name}</td>
                  <td className="py-1 font-mono text-xs">{line.identifier ?? "—"}</td>
                  <td className="py-1 text-right tabular-nums">
                    {protocol.kind === "wydanie"
                      ? line.unit_value == null
                        ? "—"
                        : formatPln(line.unit_value)
                      : line.condition
                        ? CONDITION_LABELS[line.condition]
                        : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {protocol.kind === "wydanie" ? (
            <p>
              Razem <span className="font-semibold tabular-nums">{formatPln(protocol.total_value)}</span>
            </p>
          ) : null}
          <ProtocolDownloads protocol={protocol} />

          {linkUrl ? (
            <ProtocolLinkBox url={linkUrl} number={protocol.number} email={protocol.holder.email} />
          ) : protocol.link && protocol.status === "oczekuje" ? (
            <p className="text-xs text-muted-foreground">
              Link wysłany {formatIsoDatePl(protocol.link.created_at)}, ważny do{" "}
              {formatIsoDatePl(protocol.link.expires_at)}.
            </p>
          ) : null}

          {open ? (
            <section className="space-y-3 rounded-md border border-border p-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Podpis
              </h3>
              {protocol.status === "oczekuje" ? (
                <div className="flex flex-wrap items-end gap-2">
                  <Button variant="outline" size="sm" onClick={newLink} disabled={link.isPending}>
                    {protocol.link ? "Nowy link (przypomnienie)" : "Utwórz link do podpisu"}
                  </Button>
                </div>
              ) : (
                <p className="text-xs">
                  Osoba potwierdziła odbiór{protocol.signer_name ? ` jako „${protocol.signer_name}”` : ""}.
                  Sprawdź i potwierdź podpis.
                </p>
              )}
              <div className="flex flex-wrap items-end gap-2">
                <FormField label="Sposób podpisu" htmlFor={`eq-sign-method-${protocol.id}`}>
                  <Select value={method} onValueChange={(value) => setMethod(value as PaperMethod)}>
                    <SelectTrigger id={`eq-sign-method-${protocol.id}`} className="h-9 w-48">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="papier">Papier</SelectItem>
                      <SelectItem value="profil_zaufany">Profil zaufany</SelectItem>
                    </SelectContent>
                  </Select>
                </FormField>
                <label className="inline-flex h-9 cursor-pointer items-center rounded-md border border-border px-3 text-xs hover:bg-muted">
                  {upload.isPending ? "Wgrywanie…" : "Wgraj podpisany plik"}
                  <input
                    type="file"
                    accept="application/pdf,image/jpeg,image/png"
                    className="sr-only"
                    onChange={(event) => onFile(event.target.files?.[0] ?? null)}
                  />
                </label>
                <Button size="sm" onClick={onConfirm} disabled={confirm.isPending}>
                  Potwierdź podpis
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Podpis potwierdza człowiek — automatyczna weryfikacja podpisu zaufanego bywa
                „nieokreślona”.
              </p>
            </section>
          ) : null}
          {protocol.has_signed_file ? (
            <Button variant="tertiary" size="sm" onClick={downloadSigned}>
              Pobierz podpisany plik
            </Button>
          ) : null}
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
        </div>
      )}
      {confirmDialog}
      {quick.dialogs}
      {correcting && protocol?.status === "oczekuje" ? (
        <ProtocolCorrectionDialog
          protocol={protocol}
          onClose={() => setCorrecting(false)}
          onSaved={afterCorrection}
          onCancelProtocol={cancelThis}
        />
      ) : null}
    </AppModal>
  );
}
