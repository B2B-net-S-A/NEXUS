"use client";

import { useState } from "react";
import { Download, FileUp, Pencil, Trash2 } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiErrorMessage } from "@/lib/api-error";
import {
  downloadDocument,
  downloadProtocol,
  usePersonDocuments,
  type PersonDocument,
} from "@/lib/api/hr-documents";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { EditDocumentDialog, RemoveDocumentDialog, UploadDocumentDialog } from "./DocumentDialogs";
import { documentRows, type DocumentRow } from "./documents-format";

type Dialog =
  | { kind: "upload" }
  | { kind: "edit"; document: PersonDocument }
  | { kind: "remove"; document: PersonDocument }
  | null;

function RowActions({
  row,
  canManage,
  onDownload,
  onEdit,
  onRemove,
}: {
  row: DocumentRow;
  canManage: boolean;
  onDownload: () => void;
  onEdit: (document: PersonDocument) => void;
  onRemove: (document: PersonDocument) => void;
}) {
  const document = row.document;
  const editable = canManage && document !== null && !document.deleted;
  return (
    <div className="flex justify-end gap-0.5">
      {!row.muted ? (
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Pobierz: ${row.title}`}
          onClick={onDownload}
        >
          <Download className="h-4 w-4" aria-hidden />
        </Button>
      ) : null}
      {editable ? (
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Zmień: ${row.title}`}
          onClick={() => onEdit(document)}
        >
          <Pencil className="h-4 w-4" aria-hidden />
        </Button>
      ) : null}
      {editable && document.source === "upload" ? (
        <Button
          variant="quiet"
          size="icon-sm"
          aria-label={`Usuń: ${row.title}`}
          onClick={() => onRemove(document)}
        >
          <Trash2 className="h-4 w-4" aria-hidden />
        </Button>
      ) : null}
    </div>
  );
}

/**
 * Kartoteka → „Dokumenty” (e-teczka, etap 5, E4): umowy, aneksy, oświadczenia,
 * zaświadczenia i protokoły sprzętu osoby. Kadry widzą wszystko i zmieniają;
 * osoba, Płace i recepcja widzą dokumenty ze swoim znacznikiem; przełożony nie
 * (serwer odpowiada 404 — sekcja się chowa). Protokoły to odnośniki do modułu
 * sprzętu, bez kopii pliku.
 */
export function PersonDocumentsSection({
  userId,
  name,
  enabled,
}: {
  userId: number;
  name: string;
  enabled: boolean;
}) {
  const { showToast } = useToast();
  const query = usePersonDocuments(userId, enabled);
  const [dialog, setDialog] = useState<Dialog>(null);
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (!enabled || state === "forbidden" || state === "not_found") return null;

  const data = query.data;
  const rows = data ? documentRows(data.documents, data.protocols) : [];
  const canManage = data?.can_manage ?? false;

  const download = async (row: DocumentRow) => {
    try {
      if (row.document) await downloadDocument(row.document);
      else if (row.protocol) await downloadProtocol(userId, row.protocol);
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się pobrać pliku."), "error");
    }
  };

  return (
    <Card className="space-y-3 p-4" aria-labelledby={`documents-title-${userId}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2
            id={`documents-title-${userId}`}
            className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground"
          >
            Dokumenty
          </h2>
          <span className="text-xs text-muted-foreground">
            każdy dokument ma swój krąg widzących; przełożony ich nie widzi
          </span>
        </div>
        {canManage ? (
          <Button size="sm" variant="outline" onClick={() => setDialog({ kind: "upload" })}>
            <FileUp className="h-4 w-4" aria-hidden />
            Wgraj dokument
          </Button>
        ) : null}
      </div>

      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : state !== "ready" || !data ? (
        <QueryStateNotice
          state="error"
          description="Nie udało się wczytać dokumentów."
          onRetry={() => query.refetch()}
        />
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {canManage
            ? "Ta osoba nie ma jeszcze dokumentów w NEXUSIE."
            : "Nie ma dokumentów, które możesz zobaczyć."}
        </p>
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[640px] table-fixed text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className={cn(CALM_HEAD, "w-[38%] py-2 pr-3 text-left")}>Dokument</th>
                <th className={cn(CALM_HEAD, "w-[12%] py-2 pr-3 text-left")}>Rodzaj</th>
                <th className={cn(CALM_HEAD, "w-[18%] py-2 pr-3 text-left")}>Stan</th>
                <th className={cn(CALM_HEAD, "w-[11%] py-2 pr-3 text-left")}>Ważny do</th>
                <th className={cn(CALM_HEAD, "w-[13%] py-2 pr-3 text-left")}>Widzą</th>
                <th className={cn(CALM_HEAD, "w-[8%] py-2 text-right")}>
                  <span className="sr-only">Akcje</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key} className={cn(CALM_ROW, row.muted && "text-muted-foreground")}>
                  <td className="py-2 pr-3 align-top">
                    <span className={cn("block truncate font-medium", !row.muted && "text-foreground")}>
                      {row.title}
                    </span>
                    {row.subline ? (
                      <span className={cn(CALM_SUBLINE, "truncate")}>{row.subline}</span>
                    ) : null}
                  </td>
                  <td className="py-2 pr-3 align-top">{row.kindLabel}</td>
                  <td className="py-2 pr-3 align-top">
                    <StatusDot tone={row.tone} note={row.statusNote}>
                      {row.status}
                    </StatusDot>
                  </td>
                  <td className="py-2 pr-3 align-top tabular-nums">{row.validUntil}</td>
                  <td className="py-2 pr-3 align-top">{row.audience}</td>
                  <td className="py-1.5 align-top">
                    <RowActions
                      row={row}
                      canManage={canManage}
                      onDownload={() => void download(row)}
                      onEdit={(document) => setDialog({ kind: "edit", document })}
                      onRemove={(document) => setDialog({ kind: "remove", document })}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {canManage ? (
        <p className="text-xs text-muted-foreground">
          „Ważny do” oświadczenia studenta zasila przypomnienie dla Płac 30 dni wcześniej. Po
          odejściu osoby dokumenty zostają na czas przechowywania — usuwają je Kadry z listy w
          Ustawieniach.
        </p>
      ) : null}

      {dialog?.kind === "upload" ? (
        <UploadDocumentDialog
          userId={userId}
          name={name}
          open
          onOpenChange={(open) => !open && setDialog(null)}
        />
      ) : null}
      {dialog?.kind === "edit" ? (
        <EditDocumentDialog
          document={dialog.document}
          open
          onOpenChange={(open) => !open && setDialog(null)}
        />
      ) : null}
      {dialog?.kind === "remove" ? (
        <RemoveDocumentDialog
          document={dialog.document}
          open
          onOpenChange={(open) => !open && setDialog(null)}
        />
      ) : null}
    </Card>
  );
}
