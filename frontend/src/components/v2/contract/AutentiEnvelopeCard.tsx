"use client";

import * as React from "react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bell,
  CheckCircle2,
  Clock,
  RotateCcw,
  Send,
  XCircle,
} from "lucide-react";
import { AxiosError } from "axios";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useToast } from "@/components/Toast";
import {
  autentiApi,
  type DocumentSignature,
  type SignatureStatus,
} from "@/lib/api";

import { AutentiSendDialog } from "./AutentiSendDialog";

interface Props {
  contractId: number;
  candidateName: string;
  candidatePhone: string | null;
}

const STATUS_LABEL: Record<SignatureStatus, string> = {
  draft: "Szkic",
  sending: "Wysyłanie…",
  sent: "Wysłano",
  in_progress: "W trakcie podpisywania",
  completed: "Podpisano",
  rejected: "Odrzucono",
  withdrawn: "Wycofano",
  failed: "Błąd wysyłki",
  expired: "Wygasło",
};

const STATUS_VARIANT: Record<
  SignatureStatus,
  "neutral" | "info" | "warning" | "success" | "danger"
> = {
  draft: "neutral",
  sending: "info",
  sent: "info",
  in_progress: "info",
  completed: "success",
  rejected: "danger",
  withdrawn: "neutral",
  failed: "danger",
  expired: "warning",
};

const STATUS_ICON: Record<SignatureStatus, React.ElementType> = {
  draft: Clock,
  sending: Send,
  sent: Send,
  in_progress: Clock,
  completed: CheckCircle2,
  rejected: XCircle,
  withdrawn: XCircle,
  failed: AlertTriangle,
  expired: AlertTriangle,
};

function formatTimestamp(value: string | null): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("pl-PL", {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return value;
  }
}

interface SignatureRowProps {
  signature: DocumentSignature;
  onResend: () => void;
  contractId: number;
}

function SignatureRow({
  signature,
  onResend,
  contractId,
}: SignatureRowProps) {
  const Icon = STATUS_ICON[signature.status];
  const sentAt = signature.sent_at ?? signature.created_at;
  const completedAt = signature.completed_at;
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();

  const isPending = ["sent", "in_progress"].includes(signature.status);
  const isFailed = signature.status === "failed";

  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: ["autenti-signatures", contractId],
    });

  const withdrawMutation = useMutation({
    mutationFn: () => autentiApi.withdraw(signature.id).then((r) => r.data),
    onSuccess: () => {
      showSuccess("Wycofano wysyłkę");
      invalidate();
    },
    onError: (error: unknown) => {
      const axiosError = error as AxiosError<{ detail?: string }>;
      showError(
        `Nie udało się wycofać: ${axiosError.response?.data?.detail ?? "spróbuj ponownie"}`,
      );
    },
  });

  const remindMutation = useMutation({
    mutationFn: () => autentiApi.remind(signature.id).then((r) => r.data),
    onSuccess: () => {
      showSuccess("Wysłano przypomnienie");
      invalidate();
    },
    onError: (error: unknown) => {
      const axiosError = error as AxiosError<{ detail?: string }>;
      const detail = axiosError.response?.data?.detail;
      if (axiosError.response?.status === 429) {
        showError(
          "Przypomnienie zostało już wysłane w ciągu ostatniej godziny.",
        );
      } else {
        showError(`Nie udało się przypomnieć: ${detail ?? "spróbuj ponownie"}`);
      }
    },
  });

  return (
    <div className="rounded-md border border-border bg-card p-3 space-y-2">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">
            {signature.signer_first_name} {signature.signer_last_name}
          </span>
          <span className="text-xs text-muted-foreground">
            ({signature.signer_email})
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="neutral" size="sm">
            {signature.autenti_signature_type}
          </Badge>
          <Badge variant={STATUS_VARIANT[signature.status]} size="sm">
            {STATUS_LABEL[signature.status]}
          </Badge>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs text-muted-foreground">
        <div>
          <span className="font-medium text-foreground/70">Wysłano:</span>{" "}
          {formatTimestamp(sentAt)}
        </div>
        <div>
          <span className="font-medium text-foreground/70">Wygasa:</span>{" "}
          {formatTimestamp(signature.expires_at)}
        </div>
        <div>
          <span className="font-medium text-foreground/70">Podpisano:</span>{" "}
          {formatTimestamp(completedAt)}
        </div>
      </div>

      {signature.last_error && isFailed && (
        <div className="rounded border border-red-300 bg-red-50 p-2 text-xs text-red-900">
          {signature.last_error}
        </div>
      )}

      {signature.signed_document_url && signature.status === "completed" && (
        <div>
          <a
            href={signature.signed_document_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-primary underline"
          >
            Otwórz w Autenti →
          </a>
        </div>
      )}

      {(isPending || isFailed) && (
        <div className="flex flex-wrap gap-2 pt-1">
          {isPending && (
            <>
              <Button
                size="sm"
                variant="outline"
                onClick={() => remindMutation.mutate()}
                disabled={remindMutation.isPending}
              >
                <Bell className="h-3.5 w-3.5 mr-1" />
                {remindMutation.isPending ? "Przypominam…" : "Przypomnij"}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => withdrawMutation.mutate()}
                disabled={withdrawMutation.isPending}
              >
                <XCircle className="h-3.5 w-3.5 mr-1" />
                {withdrawMutation.isPending ? "Wycofuję…" : "Wycofaj"}
              </Button>
            </>
          )}
          {isFailed && (
            <Button size="sm" variant="outline" onClick={onResend}>
              <RotateCcw className="h-3.5 w-3.5 mr-1" />
              Wyślij ponownie
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

export function AutentiEnvelopeCard({
  contractId,
  candidateName,
  candidatePhone,
}: Props) {
  const [dialogOpen, setDialogOpen] = useState(false);

  const { data, isLoading, error } = useQuery<DocumentSignature[]>({
    queryKey: ["autenti-signatures", contractId],
    queryFn: () => autentiApi.list(contractId).then((r) => r.data),
    // Backend returns 404 when AUTENTI_ENABLED=false (router not mounted).
    // Don't spam logs / retry storms — single attempt, soft-fail to "feature off".
    retry: false,
    refetchOnWindowFocus: false,
  });

  // Hide the entire card when the feature is off (404 from router not mounted).
  const axiosError = error as AxiosError | undefined;
  if (axiosError?.response?.status === 404) {
    return null;
  }

  const signatures = data ?? [];
  const hasActive = signatures.some((s) =>
    ["sent", "sending", "in_progress"].includes(s.status),
  );

  return (
    <>
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Podpisy elektroniczne (Autenti)
          </div>
          <Button
            size="sm"
            onClick={() => setDialogOpen(true)}
            disabled={hasActive}
            title={
              hasActive
                ? "Aktywna wysyłka — wycofaj lub poczekaj na status końcowy."
                : undefined
            }
          >
            <Send className="h-3.5 w-3.5 mr-1" />
            Wyślij do podpisu
          </Button>
        </div>

        {isLoading && (
          <Card variant="default" size="sm">
            <CardContent className="py-3 text-xs text-muted-foreground">
              Ładowanie historii podpisów…
            </CardContent>
          </Card>
        )}

        {!isLoading && signatures.length === 0 && (
          <Card variant="default" size="sm">
            <CardContent className="py-3 text-xs text-muted-foreground">
              Brak wysyłek. Kliknij „Wyślij do podpisu", aby skierować umowę
              do kandydata.
            </CardContent>
          </Card>
        )}

        {signatures.length > 0 && (
          <div className="space-y-2">
            {signatures.map((sig) => (
              <SignatureRow
                key={sig.id}
                signature={sig}
                contractId={contractId}
                onResend={() => setDialogOpen(true)}
              />
            ))}
          </div>
        )}
      </div>

      <AutentiSendDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        contractId={contractId}
        candidateName={candidateName}
        candidatePhone={candidatePhone}
      />
    </>
  );
}
