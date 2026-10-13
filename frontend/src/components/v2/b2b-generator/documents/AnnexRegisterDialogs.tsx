"use client";

// Okna rejestru aneksów: „Dołącz skan” podpisanego aneksu, „Powiąż
// z kontraktem” (aneks „Bez kontraktu” albo umowa z rejestru bez powiązania)
// i historia zdarzeń z dziennika.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Search } from "lucide-react";

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
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  b2bDocumentsApi,
  b2bDocumentsKeys,
  type DocumentHistoryEntry,
  type DocumentItem,
  type DocumentSubjectContract,
} from "@/lib/api/b2bDocuments";
import { formatDateTimePl, formatIsoDatePl } from "@/lib/date-pl";
import { contractStatusLabel } from "@/lib/status-labels";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";

import {
  ScanFileField,
  invalidateAfterDocumentChange,
  scanFileProblem,
} from "./DocumentDialogs";

// ── Dołącz skan ─────────────────────────────────────────────────────────────

export function AttachScanDialog({
  item,
  onClose,
}: {
  item: DocumentItem;
  onClose: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [scan, setScan] = useState<File | null>(null);
  const problem = scan ? scanFileProblem(scan) : null;
  const upload = useMutation({
    mutationFn: () => b2bDocumentsApi.uploadSignedScan(item.id, scan as File),
    onSuccess: () => {
      toast.showSuccess("Skan zapisany w Dokumentach kontraktu.");
      invalidateAfterDocumentChange(queryClient);
      onClose();
    },
  });
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {item.signed_scan_document_id ? "Podmień skan" : "Dołącz skan"}
          </DialogTitle>
          <DialogDescription>{item.label}</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <ScanFileField
            id={`b2b-annex-scan-${item.id}`}
            file={scan}
            onFile={setScan}
            disabled={upload.isPending}
          />
          {item.signed_scan_document_id ? (
            <p className="text-xs text-muted-foreground">
              Nowy plik zastąpi skan, który jest już w Dokumentach kontraktu.
            </p>
          ) : null}
          {upload.isError ? (
            <Alert
              variant="error"
              title="Nie udało się zapisać skanu"
              description={apiErrorMessage(upload.error, "Spróbuj ponownie.")}
            />
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            onClick={() => upload.mutate()}
            disabled={!scan || Boolean(problem) || upload.isPending}
            loading={upload.isPending}
          >
            Zapisz skan
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Powiąż z kontraktem ─────────────────────────────────────────────────────

function contractOptionLabel(option: DocumentSubjectContract, who: string): string {
  return [
    `Kontrakt #${option.contract_id}`,
    who,
    contractStatusLabel(option.status).toLocaleLowerCase("pl"),
    option.start_date ? `od ${formatIsoDatePl(option.start_date)}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

export function LinkContractDialog({
  item,
  onClose,
}: {
  item: DocumentItem;
  onClose: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const parentId = item.parent_generated_contract_id;
  // Aneks do umowy z rejestru: kontrakty tej umowy. Aneks bez umowy:
  // wyszukiwanie osoby, jak przy tworzeniu aneksu.
  const [query, setQuery] = useState(
    parentId
      ? (item.parent_contract_number ?? "")
      : (item.person_name ?? item.partner_name ?? ""),
  );
  const q = useDebouncedValue(query, 300).trim();
  const [picked, setPicked] = useState<number | null>(null);
  const found = useQuery({
    queryKey: b2bDocumentsKeys.subjects(item.document_type, q),
    queryFn: () => b2bDocumentsApi.subjects({ documentType: item.document_type, q }),
    enabled: q.length >= 2,
    staleTime: 10_000,
  });
  const options: { contract: DocumentSubjectContract; who: string }[] = (
    found.data ?? []
  ).flatMap((subject) => {
    const who = [subject.person_name, subject.client_name].filter(Boolean).join(" · ");
    if (parentId) {
      return subject.parent_generated_contract_id === parentId
        ? subject.contract_options.map((contract) => ({ contract, who }))
        : [];
    }
    return subject.kind === "contract" && subject.contract_id !== null
      ? [
          {
            contract: {
              contract_id: subject.contract_id,
              status: subject.contract_status ?? "",
              start_date: subject.contract_start_date,
            },
            who,
          },
        ]
      : [];
  });
  const link = useMutation({
    mutationFn: () => b2bDocumentsApi.linkContract(item.id, picked as number),
    onSuccess: () => {
      toast.showSuccess("Aneks powiązany z kontraktem.");
      invalidateAfterDocumentChange(queryClient);
      onClose();
    },
  });

  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Powiąż z kontraktem</DialogTitle>
          <DialogDescription>
            {item.label}. Po podpisie aneks zmieni wskazany kontrakt.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          {parentId ? null : (
            <div className="space-y-1">
              <Label htmlFor={`b2b-annex-link-${item.id}`}>
                Osoba, firma albo NIP
              </Label>
              <div className="relative">
                <Search
                  className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground"
                  aria-hidden="true"
                />
                <Input
                  id={`b2b-annex-link-${item.id}`}
                  className="w-full pl-8"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setPicked(null);
                  }}
                />
              </div>
            </div>
          )}
          {q.length < 2 ? (
            <p className="text-sm text-muted-foreground">
              Wpisz co najmniej dwa znaki.
            </p>
          ) : found.isPending ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Szukam kontraktów…
            </p>
          ) : found.isError ? (
            <Alert
              variant="error"
              title="Nie udało się wczytać kontraktów"
              description={apiErrorMessage(found.error, "Spróbuj ponownie.")}
            >
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => void found.refetch()}
              >
                Ponów
              </Button>
            </Alert>
          ) : found.isSuccess && options.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {parentId
                ? "Osoba z tej umowy nie ma u tego klienta trwającego kontraktu B2B bez własnej umowy w rejestrze."
                : "Nie znaleźliśmy kontraktu bez umowy w rejestrze pasującego do wyszukiwania."}
            </p>
          ) : (
            <ul className="max-h-72 space-y-2 overflow-y-auto">
              {options.map(({ contract, who }) => (
                <li key={contract.contract_id}>
                  <button
                    type="button"
                    aria-pressed={picked === contract.contract_id}
                    onClick={() => setPicked(contract.contract_id)}
                    className={cn(
                      "w-full rounded-lg border px-3 py-2 text-left text-sm hover:bg-muted",
                      picked === contract.contract_id
                        ? "border-primary bg-primary/5"
                        : "border-border bg-card",
                    )}
                  >
                    {contractOptionLabel(contract, who)}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {link.isError ? (
            <Alert
              variant="error"
              title="Nie udało się powiązać aneksu"
              description={apiErrorMessage(link.error, "Spróbuj ponownie.")}
            />
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            onClick={() => link.mutate()}
            disabled={picked === null || link.isPending}
            loading={link.isPending}
          >
            Powiąż
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Historia ────────────────────────────────────────────────────────────────

const HISTORY_LABELS: Record<string, string> = {
  generated: "Wygenerowano",
  regenerated: "Poprawiono treść",
  cancelled: "Anulowano",
  restored: "Przywrócono",
  contract_linked: "Powiązano z kontraktem",
  signed_effect_applied: "Oznaczono jako podpisany",
  signed_scan_attached: "Dołączono skan",
};

export function annexHistoryLabel(entry: Pick<DocumentHistoryEntry, "action">): string {
  return HISTORY_LABELS[entry.action] ?? "Zdarzenie";
}

export function AnnexHistoryDialog({
  item,
  onClose,
}: {
  item: DocumentItem;
  onClose: () => void;
}) {
  const history = useQuery({
    queryKey: b2bDocumentsKeys.history(item.id),
    queryFn: () => b2bDocumentsApi.history(item.id),
    staleTime: 0,
  });
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Historia aneksu</DialogTitle>
          <DialogDescription>{item.label}</DialogDescription>
        </DialogHeader>
        <DialogBody>
          {history.isPending ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Wczytuję historię…
            </p>
          ) : history.isError ? (
            <Alert
              variant="error"
              title="Nie udało się wczytać historii"
              description={apiErrorMessage(history.error, "Spróbuj ponownie.")}
            >
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => void history.refetch()}
              >
                Ponów
              </Button>
            </Alert>
          ) : history.isSuccess && history.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Ten aneks nie ma jeszcze zapisanych zdarzeń.
            </p>
          ) : (
            <ol className="space-y-3 text-sm">
              {(history.data ?? []).map((entry, index) => (
                <li key={`${entry.action}-${entry.at}-${index}`}>
                  <div className="font-medium text-foreground">
                    {annexHistoryLabel(entry)}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {[entry.at ? formatDateTimePl(entry.at) : "", entry.by_name ?? ""]
                      .filter(Boolean)
                      .join(" · ") || "—"}
                  </div>
                  {entry.note ? (
                    <div className="text-xs text-muted-foreground">
                      Powód: {entry.note}
                    </div>
                  ) : null}
                </li>
              ))}
            </ol>
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Zamknij
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
