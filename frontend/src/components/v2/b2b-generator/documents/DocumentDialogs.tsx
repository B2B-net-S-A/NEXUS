"use client";

// Okna listy dokumentów: „Oznacz jako podpisany” (ze skutkami liczonymi przez
// serwer), ponowne pobranie z danymi wrażliwymi, anulowanie, usunięcie oraz
// rejestracja wypowiedzenia od Partnera. Bez `window.confirm` — natywny dialog
// zamraża automatyzację przeglądarki i nie da się go przeklikać w testach.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Ban, CheckCircle2, Loader2 } from "lucide-react";

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
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  B2B_DOCUMENTS_KEY,
  b2bDocumentsApi,
  b2bDocumentsKeys,
  type DocumentEffects,
  type DocumentItem,
  type DocumentTypeDef,
  type DocumentValue,
  type DocumentValues,
} from "@/lib/api/b2bDocuments";
import {
  fieldKeysForLabels,
  readDocumentError,
  sensitiveFieldsOf,
} from "@/lib/b2b-documents";
import { downloadBlob, parseDispositionFilename } from "@/lib/cv-generator";
import { warsawToday } from "@/lib/warsaw-date";

import { DocumentFieldsForm } from "./DocumentFieldsForm";

/** Po zmianie dokumentu albo jego skutków odśwież listę, rejestr i kontrakt. */
export function invalidateAfterDocumentChange(
  queryClient: ReturnType<typeof useQueryClient>,
) {
  queryClient.invalidateQueries({ queryKey: [B2B_DOCUMENTS_KEY] });
  queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
  queryClient.invalidateQueries({ queryKey: ["contract"] });
  queryClient.invalidateQueries({ queryKey: ["contract-amendments"] });
  queryClient.invalidateQueries({ queryKey: ["contractors-v2"] });
  queryClient.invalidateQueries({ queryKey: ["contractors-stats-v2"] });
}

/** Zapisz odpowiedź DOCX jako plik. */
export function saveDocx(
  res: { data: unknown; headers: Record<string, unknown> },
  fallback: string,
) {
  const disposition = String(res.headers?.["content-disposition"] ?? "");
  downloadBlob(res.data as Blob, parseDispositionFilename(disposition, fallback));
}

// ── Oznacz jako podpisany ───────────────────────────────────────────────────

export function EffectsView({ effects }: { effects: DocumentEffects }) {
  return (
    <div className="space-y-4 text-sm">
      <p className="text-muted-foreground">{effects.effect_label}</p>
      {effects.changes.length ? (
        <div>
          <h3 className="mb-1 font-medium text-foreground">Co się zmieni</h3>
          <ul className="space-y-1">
            {effects.changes.map((c) => (
              <li key={c} className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                <span>{c}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {effects.warnings.length ? (
        <div>
          <h3 className="mb-1 font-medium text-foreground">Ostrzeżenia</h3>
          <ul className="space-y-1">
            {effects.warnings.map((w) => (
              <li key={w} className="flex items-start gap-2 text-warning-muted-foreground">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                <span>{w}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {effects.blockers.length ? (
        <div role="alert">
          <h3 className="mb-1 font-medium text-destructive">
            Tego dokumentu nie da się teraz oznaczyć jako podpisanego
          </h3>
          <ul className="space-y-1">
            {effects.blockers.map((b) => (
              <li key={b} className="flex items-start gap-2 text-destructive">
                <Ban className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                <span>{b}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function ConfirmSignedDialog({
  item,
  onClose,
}: {
  item: DocumentItem;
  onClose: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const effects = useQuery({
    queryKey: b2bDocumentsKeys.effects(item.id),
    queryFn: () => b2bDocumentsApi.effects(item.id),
    staleTime: 0,
  });
  const confirm = useMutation({
    mutationFn: () => b2bDocumentsApi.confirmSigned(item.id),
    onSuccess: () => {
      toast.showSuccess("Dokument oznaczony jako podpisany — skutki zastosowane.");
      invalidateAfterDocumentChange(queryClient);
      onClose();
    },
  });
  const blocked = (effects.data?.blockers.length ?? 0) > 0;
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Oznacz jako podpisany</DialogTitle>
          <DialogDescription>{item.label}</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          {effects.isPending ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Sprawdzam, co zmieni podpis…
            </p>
          ) : effects.isError ? (
            <Alert
              variant="error"
              title="Nie udało się sprawdzić skutków podpisu"
              description={apiErrorMessage(effects.error, "Spróbuj ponownie za chwilę.")}
            >
              <Button variant="outline" size="sm" className="mt-2" onClick={() => void effects.refetch()}>
                Ponów
              </Button>
            </Alert>
          ) : effects.data ? (
            <EffectsView effects={effects.data} />
          ) : null}
          {confirm.isError ? (
            <Alert
              variant="error"
              title="Nie udało się oznaczyć dokumentu"
              description={apiErrorMessage(confirm.error, "Spróbuj ponownie.")}
            />
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            onClick={() => confirm.mutate()}
            disabled={!effects.isSuccess || blocked || confirm.isPending}
            loading={confirm.isPending}
          >
            Potwierdź podpis obu stron
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Ponowne pobranie z danymi wrażliwymi ────────────────────────────────────

export function RedownloadDialog({
  item,
  type,
  onClose,
}: {
  item: DocumentItem;
  type: DocumentTypeDef | undefined;
  onClose: () => void;
}) {
  const toast = useToast();
  const fields = sensitiveFieldsOf(type, item.sensitive_fields);
  const [values, setValues] = useState<DocumentValues>({});
  const [errorKeys, setErrorKeys] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const download = useMutation({
    mutationFn: async () => {
      const res = await b2bDocumentsApi.redownload(item.id, values);
      saveDocx(res, `${item.type_label}.docx`);
    },
    onSuccess: () => {
      toast.showSuccess("Dokument pobrany.");
      onClose();
    },
    onError: async (e) => {
      const parsed = await readDocumentError(e, "Nie udało się pobrać dokumentu.");
      setError(parsed.message);
      if (type) setErrorKeys(new Set(fieldKeysForLabels(type, parsed.missing)));
    },
  });
  // Formularz tylko z polami wrażliwymi, w jednej grupie.
  const sensitiveType: DocumentTypeDef | undefined = type
    ? { ...type, fields: fields.map((f) => ({ ...f, group: "partner" as const, show_if: null })) }
    : undefined;
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Pobierz dokument ponownie</DialogTitle>
          <DialogDescription>
            Tych danych nie przechowujemy — podaj je, żeby trafiły do pliku.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <p className="text-sm text-muted-foreground">{item.label}</p>
          {sensitiveType ? (
            <DocumentFieldsForm
              type={sensitiveType}
              values={values}
              errorKeys={errorKeys}
              idPrefix={`b2b-doc-redownload-${item.id}`}
              onChange={(key: string, value: DocumentValue) => {
                setValues((prev) => ({ ...prev, [key]: value }));
                setErrorKeys((prev) => {
                  const next = new Set(prev);
                  next.delete(key);
                  return next;
                });
              }}
            />
          ) : (
            <p className="text-sm text-muted-foreground">Wczytuję pola dokumentu…</p>
          )}
          {error ? <Alert variant="error" title={error} /> : null}
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            onClick={() => {
              setError(null);
              download.mutate();
            }}
            disabled={download.isPending || !sensitiveType}
            loading={download.isPending}
          >
            Pobierz DOCX
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Anuluj / usuń ───────────────────────────────────────────────────────────

export function CancelDocumentDialog({
  item,
  mode,
  onClose,
}: {
  item: DocumentItem;
  mode: "cancel" | "delete";
  onClose: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      mode === "cancel"
        ? b2bDocumentsApi.cancel(item.id, reason.trim()).then(() => undefined)
        : b2bDocumentsApi.remove(item.id),
    onSuccess: () => {
      toast.showSuccess(mode === "cancel" ? "Dokument anulowany." : "Dokument usunięty.");
      invalidateAfterDocumentChange(queryClient);
      onClose();
    },
  });
  const reasonId = `b2b-doc-cancel-reason-${item.id}`;
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent size="md">
        <DialogHeader>
          <DialogTitle>
            {mode === "cancel" ? "Anuluj dokument" : "Usuń dokument"}
          </DialogTitle>
          <DialogDescription>{item.label}</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3">
          {mode === "cancel" ? (
            <>
              <p className="text-sm text-muted-foreground">
                Dokument, który nie doszedł do skutku, zostaje w historii
                z powodem anulowania.
              </p>
              <div className="space-y-1">
                <Label htmlFor={reasonId}>Powód anulowania *</Label>
                <Textarea
                  id={reasonId}
                  rows={3}
                  maxLength={500}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </div>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              Dokument zniknie z listy. Jeśli trafił już do Partnera, lepiej go
              anulować — zostanie w historii.
            </p>
          )}
          {mutation.isError ? (
            <Alert
              variant="error"
              title={apiErrorMessage(mutation.error, "Nie udało się zapisać zmiany.")}
            />
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Wróć
          </Button>
          <Button
            variant="destructive"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || (mode === "cancel" && !reason.trim())}
            loading={mutation.isPending}
          >
            {mode === "cancel" ? "Anuluj dokument" : "Usuń dokument"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Wypowiedzenie od Partnera ───────────────────────────────────────────────

export function PartnerNoticeDialog({
  parentId,
  contractNumber,
  partnerName,
  onClose,
}: {
  parentId: number;
  contractNumber: string;
  partnerName?: string | null;
  onClose: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [deliveredOn, setDeliveredOn] = useState(warsawToday());
  const [terminationDate, setTerminationDate] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      b2bDocumentsApi.partnerNotice({
        parent_generated_contract_id: parentId,
        delivered_on: deliveredOn,
        termination_date: terminationDate || null,
      }),
    onSuccess: (result) => {
      toast.showSuccess(
        `Wypowiedzenie zarejestrowane — umowa rozwiąże się ${result.termination_date.split("-").reverse().join(".")}.`,
      );
      invalidateAfterDocumentChange(queryClient);
      onClose();
    },
  });
  const tooEarly = Boolean(terminationDate && deliveredOn && terminationDate < deliveredOn);
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent size="md">
        <DialogHeader>
          <DialogTitle>Zarejestruj wypowiedzenie Partnera</DialogTitle>
          <DialogDescription>
            Umowa {contractNumber}
            {partnerName ? ` — ${partnerName}` : ""}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Partner złożył wypowiedzenie — NEXUS zapisze fakt i jego skutek:
            kontrakt dostanie datę zakończenia, a umowa w rejestrze status
            „Zakończona”. Dokumentu po naszej stronie nie ma.
          </p>
          <div className="space-y-1">
            <Label htmlFor="b2b-partner-notice-delivered">Data doręczenia wypowiedzenia *</Label>
            <Input
              id="b2b-partner-notice-delivered"
              type="date"
              value={deliveredOn}
              onChange={(e) => setDeliveredOn(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="b2b-partner-notice-end">Data rozwiązania umowy</Label>
            <Input
              id="b2b-partner-notice-end"
              type="date"
              value={terminationDate}
              aria-describedby="b2b-partner-notice-end-help"
              onChange={(e) => setTerminationDate(e.target.value)}
            />
            <p id="b2b-partner-notice-end-help" className="text-xs text-muted-foreground">
              Zostaw puste — policzymy ją z okresu wypowiedzenia w umowie.
            </p>
            {tooEarly ? (
              <p className="text-xs text-destructive">
                Data rozwiązania nie może być wcześniejsza niż doręczenie.
              </p>
            ) : null}
          </div>
          {mutation.isError ? (
            <Alert
              variant="error"
              title={apiErrorMessage(mutation.error, "Nie udało się zarejestrować wypowiedzenia.")}
            />
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            onClick={() => mutation.mutate()}
            disabled={!deliveredOn || tooEarly || mutation.isPending}
            loading={mutation.isPending}
          >
            Zarejestruj
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
