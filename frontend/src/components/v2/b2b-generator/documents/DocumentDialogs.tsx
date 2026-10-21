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
  // Aneks widać w kontrakcie od wygenerowania, a skan trafia do jego Dokumentów.
  queryClient.invalidateQueries({ queryKey: ["contract-annex-documents"] });
  queryClient.invalidateQueries({ queryKey: ["contract-documents"] });
  queryClient.invalidateQueries({ queryKey: ["contractors-v2"] });
  queryClient.invalidateQueries({ queryKey: ["contractors-stats-v2"] });
}

/** Skan podpisanego aneksu: PDF albo zdjęcie, do 20 MB (serwer sprawdza to samo). */
export const SCAN_ACCEPT = ".pdf,.jpg,.jpeg,.png";
const SCAN_MAX_BYTES = 20 * 1024 * 1024;

const SCAN_FORMAT_MESSAGE =
  "Skan podpisanego aneksu musi być plikiem PDF, JPG albo PNG.";

/** Powód odrzucenia pliku przed wysyłką albo `null`, gdy plik się nadaje. */
export function scanFileProblem(
  file: File,
  formatMessage: string = SCAN_FORMAT_MESSAGE,
): string | null {
  if (!/\.(pdf|jpe?g|png)$/i.test(file.name)) {
    return formatMessage;
  }
  if (file.size > SCAN_MAX_BYTES) {
    return "Plik jest za duży — skan może mieć najwyżej 20 MB.";
  }
  if (file.size === 0) return "Plik jest pusty.";
  return null;
}

/** Pole wyboru skanu — wspólne dla okien podpisu aneksu i umowy oraz „Dołącz skan”. */
export function ScanFileField({
  id,
  file,
  onFile,
  disabled = false,
  label = "Skan podpisanego aneksu",
  formatMessage = SCAN_FORMAT_MESSAGE,
}: {
  id: string;
  file: File | null;
  onFile: (file: File | null) => void;
  disabled?: boolean;
  label?: string;
  formatMessage?: string;
}) {
  const problem = file ? scanFileProblem(file, formatMessage) : null;
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="file"
        accept={SCAN_ACCEPT}
        disabled={disabled}
        aria-invalid={problem ? true : undefined}
        aria-describedby={`${id}-hint`}
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
      />
      <p id={`${id}-hint`} className="text-xs text-muted-foreground">
        PDF, JPG albo PNG, do 20 MB. Trafi do Dokumentów kontraktu.
      </p>
      {problem ? (
        <p role="alert" className="text-xs text-destructive">
          {problem}
        </p>
      ) : null}
    </div>
  );
}

/** Zapisz odpowiedź z plikiem (DOCX albo PDF) na dysku. */
export function saveDocx(
  res: { data: unknown; headers: Record<string, unknown> },
  fallback: string,
) {
  const disposition = String(res.headers?.["content-disposition"] ?? "");
  downloadBlob(res.data as Blob, parseDispositionFilename(disposition, fallback));
}

export type DocumentFileFormat = "docx" | "pdf";

/**
 * PDF oferujemy przy umowach przedwstępnych — idą do kandydata, który podpisuje
 * je dowolną formą (także podpisem zaufanym); pozostałe dokumenty — DOCX.
 */
export function offersPdf(item: Pick<DocumentItem, "family">): boolean {
  return item.family === "preliminary";
}

/** Pobierz wydany dokument w wybranym formacie (dane wrażliwe tylko w żądaniu). */
export async function downloadDocumentFile(
  item: Pick<DocumentItem, "id" | "type_label">,
  format: DocumentFileFormat,
  values: DocumentValues = {},
) {
  const res =
    format === "pdf"
      ? await b2bDocumentsApi.pdf(item.id, values)
      : await b2bDocumentsApi.redownload(item.id, values);
  saveDocx(
    res as { data: unknown; headers: Record<string, unknown> },
    `${item.type_label}.${format}`,
  );
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
  // Skan ma sens tylko przy aneksie z kontraktem — trafia do jego Dokumentów.
  const takesScan = item.family === "annex" && Boolean(item.contract_id);
  const [scan, setScan] = useState<File | null>(null);
  const scanProblem = scan ? scanFileProblem(scan) : null;
  const confirm = useMutation({
    mutationFn: async () => {
      await b2bDocumentsApi.confirmSigned(item.id);
      if (!scan) return { scanError: null };
      // Podpis jest już zapisany — nieudana wysyłka skanu go nie cofa, skan
      // da się dołączyć z rejestru aneksów.
      try {
        await b2bDocumentsApi.uploadSignedScan(item.id, scan);
        return { scanError: null };
      } catch (error) {
        return {
          scanError: apiErrorMessage(error, "Nie udało się zapisać skanu."),
        };
      }
    },
    onSuccess: ({ scanError }) => {
      if (scanError) {
        toast.showError(
          `Dokument oznaczony jako podpisany, ale skan nie został zapisany: ${scanError} Dołącz go z rejestru aneksów („Dołącz skan”).`,
        );
      } else {
        toast.showSuccess("Dokument oznaczony jako podpisany — skutki zastosowane.");
      }
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
          {takesScan && effects.isSuccess && !blocked ? (
            <div className="space-y-1">
              <ScanFileField
                id={`b2b-doc-scan-${item.id}`}
                file={scan}
                onFile={setScan}
                disabled={confirm.isPending}
              />
              <p className="text-xs text-muted-foreground">
                Opcjonalnie. Bez skanu w Dokumentach kontraktu zostanie
                wygenerowany plik bez podpisów — skan dołączysz później.
              </p>
            </div>
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
            disabled={
              !effects.isSuccess ||
              blocked ||
              confirm.isPending ||
              Boolean(scanProblem)
            }
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
    mutationFn: async (format: DocumentFileFormat) => {
      await downloadDocumentFile(item, format, values);
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
          {offersPdf(item) ? (
            <Button
              variant="outline"
              onClick={() => {
                setError(null);
                download.mutate("pdf");
              }}
              disabled={download.isPending || !sensitiveType}
              loading={download.isPending && download.variables === "pdf"}
            >
              Pobierz PDF
            </Button>
          ) : null}
          <Button
            onClick={() => {
              setError(null);
              download.mutate("docx");
            }}
            disabled={download.isPending || !sensitiveType}
            loading={download.isPending && download.variables === "docx"}
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
  noticePeriodKnown = true,
  contractLinked = true,
  onClose,
}: {
  parentId: number;
  contractNumber: string;
  partnerName?: string | null;
  /**
   * Umowa ma znaną wersję wzoru — serwer policzy datę rozwiązania z okresu
   * wypowiedzenia. Bez wersji (wiersz z Excela działu) data jest wymagana:
   * serwer nie zgaduje jej z umowy 2026 (runda 6 audytu, DOC-3).
   */
  noticePeriodKnown?: boolean;
  /**
   * Umowa ma powiązany kontrakt. Bez niego (wiersz z Excela działu) serwer
   * szuka trwającego kontraktu osoby u klienta umowy — okno nie może obiecać,
   * że kontrakt dostanie datę zakończenia (runda 10, R10-N14-3).
   */
  contractLinked?: boolean;
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
      const when = result.termination_date.split("-").reverse().join(".");
      toast.showSuccess(
        result.contract_warning
          ? `Wypowiedzenie zarejestrowane — umowa rozwiąże się ${when}. ${result.contract_warning}`
          : `Wypowiedzenie zarejestrowane — umowa rozwiąże się ${when}.`,
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
            {contractLinked
              ? "Partner złożył wypowiedzenie — NEXUS zapisze fakt i jego skutek: kontrakt dostanie datę zakończenia, a umowa w rejestrze status „Zakończona”. Dokumentu po naszej stronie nie ma."
              : "Partner złożył wypowiedzenie — NEXUS zapisze fakt i jego skutek w rejestrze umów (status „Zakończona”). Umowa nie jest powiązana z kontraktem: datę zakończenia dostanie trwający kontrakt tej osoby u tego klienta, jeśli jest jeden; bez niego zmieni się tylko rejestr. Dokumentu po naszej stronie nie ma."}
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
            <Label htmlFor="b2b-partner-notice-end">
              Data rozwiązania umowy{noticePeriodKnown ? "" : " *"}
            </Label>
            <Input
              id="b2b-partner-notice-end"
              type="date"
              value={terminationDate}
              aria-describedby="b2b-partner-notice-end-help"
              onChange={(e) => setTerminationDate(e.target.value)}
            />
            <p id="b2b-partner-notice-end-help" className="text-xs text-muted-foreground">
              {noticePeriodKnown
                ? "Zostaw puste — policzymy ją z okresu wypowiedzenia w umowie."
                : "Ta umowa nie ma w NEXUSIE wersji wzoru — wpisz datę rozwiązania wynikającą z okresu wypowiedzenia w umowie."}
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
            disabled={
              !deliveredOn ||
              tooEarly ||
              (!noticePeriodKnown && !terminationDate) ||
              mutation.isPending
            }
            loading={mutation.isPending}
          >
            Zarejestruj
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
