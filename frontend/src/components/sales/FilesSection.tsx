"use client";

import { useRef } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useDeleteSalesFile,
  useSalesFiles,
  useUploadSalesFile,
  type FileOwner,
  type SalesFile,
} from "@/lib/api/sales";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import { formatDateTimePl } from "@/lib/date-pl";
import { hasPermission } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

const ACCEPT = ".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.png,.jpg,.jpeg,.eml,.msg";

/** „1,2 MB”, „340 kB”. */
export function fileSize(bytes: number | null): string {
  if (!bytes) return "—";
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toLocaleString("pl-PL", { maximumFractionDigits: 1 })} MB`;
  }
  return `${Math.max(1, Math.round(bytes / 1024))} kB`;
}

/** Pliki w folderach (w Atlasie foldery przy szansie: „Oferta”, „Umowa”…); bez folderu na końcu. */
export function groupByFolder(files: SalesFile[]): [string, SalesFile[]][] {
  const groups = new Map<string, SalesFile[]>();
  for (const file of files) {
    const key = file.folder ?? "";
    groups.set(key, [...(groups.get(key) ?? []), file]);
  }
  return [...groups.entries()].sort(([a], [b]) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b, "pl")));
}

/** Pliki przy firmie (razem z plikami jej szans) albo przy szansie. */
export function FilesSection({ owner }: { owner: FileOwner }) {
  const files = useSalesFiles(owner);
  const upload = useUploadSalesFile(owner);
  const remove = useDeleteSalesFile();
  const input = useRef<HTMLInputElement>(null);
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showError, showSuccess } = useToast();
  const items = files.data ?? [];
  const state = resolveViewState({
    isLoading: files.isLoading,
    error: files.error,
    isSuccess: files.isSuccess,
    isEmpty: items.length === 0,
  });

  const onDelete = async (file: SalesFile) => {
    const ok = await askConfirm({
      title: `Usunąć plik „${file.filename}”?`,
      description: "Plik zniknie z firmy i szansy.",
      confirmLabel: "Usuń",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(file.id, {
      onError: (error) => showError(apiErrorMessage(error, "Nie udało się usunąć pliku.")),
    });
  };

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-foreground">Pliki</h2>
        {canEdit && (
          <>
            <input
              ref={input}
              type="file"
              accept={ACCEPT}
              className="sr-only"
              aria-label="Wybierz plik"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (!file) return;
                upload.mutate(file, {
                  onSuccess: () => showSuccess(`Dodano plik ${file.name}.`),
                  onError: (error) => showError(apiErrorMessage(error, "Nie udało się dodać pliku.")),
                });
              }}
            />
            <Button size="sm" variant="outline" loading={upload.isPending} onClick={() => input.current?.click()}>
              Dodaj plik
            </Button>
          </>
        )}
      </div>
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie plików…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void files.refetch()} />
      ) : state === "empty" ? (
        <p className="text-sm text-muted-foreground">Nie ma jeszcze plików.</p>
      ) : (
        <div className="space-y-3">
          {groupByFolder(items).map(([folder, files]) => (
            <div key={folder || "—"}>
              {folder && (
                <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{folder}</h3>
              )}
              <ul className="divide-y divide-border">
                {files.map((file) => (
                <li key={file.id} className="group flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                  <div className="min-w-0">
                    <button
                      type="button"
                      className="truncate text-left font-medium text-primary hover:underline"
                      onClick={() =>
                        void downloadAuthenticatedFile(`/api/sales/files/${file.id}/download`, file.filename).catch(
                          (error: unknown) => showError(apiErrorMessage(error, "Nie udało się pobrać pliku.")),
                        )
                      }
                    >
                      {file.filename}
                    </button>
                    <p className="text-xs text-muted-foreground">
                      {fileSize(file.size_bytes)} · {formatDateTimePl(file.created_at)}
                      {file.uploaded_by ? ` · ${file.uploaded_by}` : ""}
                    </p>
                  </div>
                  {canEdit && file.uploaded_by_user_id === user?.id && (
                    <Button
                      size="sm"
                      variant="quiet"
                      className="pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 focus-within:opacity-100"
                      onClick={() => void onDelete(file)}
                    >
                      Usuń
                    </Button>
                  )}
                </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
      {confirmDialog}
    </Card>
  );
}
