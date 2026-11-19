"use client";
// B · Dokumenty — „Jedna tabela z filtrem rodzaju”. Rejestrowo i gęsto:
// jednolinijkowe pole „Przeciągnij pliki” zamiast przycisków, pigułki rodzaju
// z licznikami zamiast przewijania 23 wierszy, jedna zwarta tabela (wiersz
// ok. 40 px, jedna linia) z rodzajem i datą z dokumentu. Data importu, autor
// i plakietka „z SharePointa” nie powtarzają się w wierszach — import opisuje
// jedna linia pod tabelą, a szczegóły pliku są w podpowiedzi przy nazwie.
// Klasyfikacja, daty z nazwy i odczyty: `DokumentyA.tsx`.
import { useMemo, useState } from "react";
import { Folder, FolderPlus, Upload } from "lucide-react";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { useMkDocuments } from "../shared/data";
import { fmtDate } from "../shared/format";
import {
  buildDocRows,
  DocIcon,
  DocRowActions,
  docDateLabel,
  fmtSize,
  GROUP_ORDER,
  httpStatus,
  batchSentence,
  sharePointBatch,
  useMkDocFolders,
  useMkOrderFiles,
  type DocGroupKey,
  type DocRow,
} from "./DokumentyA";
import type { TabProps } from "./types";

const PILL_LABEL: Record<DocGroupKey, string> = {
  umowy: "Umowy",
  aneksy: "Aneksy",
  zamowienia: "Zamówienia",
  inne: "Inne",
};

type Filter = "all" | DocGroupKey | `folder-${number}`;

function addedLine(r: DocRow): string {
  const how =
    r.origin === "import"
      ? "import z SharePointa"
      : r.origin === "sharepoint"
        ? "z SharePointa"
        : r.origin === "orders"
          ? "z zakładki Zamówienia"
          : null;
  return ["Dodano", fmtDate(r.addedDay), how, r.addedBy].filter(Boolean).join(" · ");
}

function Pill({
  active,
  onClick,
  children,
  count,
  title,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  count: number;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={title}
      className={cn(
        "inline-flex h-7 max-w-[220px] shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-[12.5px] transition-colors",
        active
          ? "border-primary/40 bg-primary/10 font-medium text-primary"
          : "border-border bg-card text-foreground hover:bg-muted",
      )}
    >
      {children}
      <span className={cn("tabular-nums", active ? "text-primary/70" : "text-muted-foreground")}>{count}</span>
    </button>
  );
}

export function DokumentyB({ contractId }: TabProps) {
  const docsQ = useMkDocuments(contractId);
  const foldersQ = useMkDocFolders(contractId);
  const ordersQ = useMkOrderFiles(contractId);
  const [filter, setFilter] = useState<Filter>("all");
  const [dragging, setDragging] = useState(false);

  const rows = useMemo(() => buildDocRows(docsQ.data ?? [], ordersQ.data ?? []), [docsQ.data, ordersQ.data]);
  const folders = foldersQ.data?.folders ?? [];
  const folderName = new Map(folders.map((f) => [f.id, f.name]));
  const inFolder = (r: DocRow) => r.folderId != null && folderName.has(r.folderId);
  const batch = sharePointBatch(rows);

  const pills = [
    ...GROUP_ORDER.map((g) => ({
      key: g as Filter,
      label: PILL_LABEL[g],
      count: rows.filter((r) => r.group === g && !inFolder(r)).length,
      folder: false,
    })),
    ...folders.map((f) => ({
      key: `folder-${f.id}` as Filter,
      label: f.name,
      count: rows.filter((r) => r.folderId === f.id).length,
      folder: true,
    })),
  ].filter((p) => p.count > 0 || p.folder);

  const visible = rows.filter((r) => {
    if (filter === "all") return true;
    if (filter.startsWith("folder-")) return r.folderId === Number(filter.slice(7));
    return r.group === filter && !inFolder(r);
  });

  return (
    <div className="space-y-2.5">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
        }}
        className={cn(
          "flex h-10 items-center gap-2 rounded-lg border border-dashed px-3 text-[12.5px] text-muted-foreground transition-colors",
          dragging ? "border-primary bg-primary/5" : "border-border bg-card",
        )}
      >
        <Upload className="size-4 shrink-0" aria-hidden />
        <span className="truncate">
          Przeciągnij pliki tutaj albo{" "}
          <button type="button" className="font-medium text-primary hover:underline">
            wybierz z dysku
          </button>{" "}
          · kopia trafi do SharePointa (poza zamówieniami klienta)
        </span>
      </div>

      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5" role="group" aria-label="Rodzaj dokumentu">
          <Pill active={filter === "all"} onClick={() => setFilter("all")} count={rows.length}>
            Wszystkie
          </Pill>
          {pills.map((p) => (
            <Pill
              key={p.key}
              active={filter === p.key}
              onClick={() => setFilter(p.key)}
              count={p.count}
              title={p.folder ? `Folder „${p.label}” — archiwum, pliki nie zapalają alarmu wygasania` : undefined}
            >
              {p.folder ? <Folder className="size-3.5 shrink-0" aria-hidden /> : null}
              <span className="truncate">{p.label}</span>
            </Pill>
          ))}
        </div>
        <Button type="button" variant="ghost" size="sm" className="shrink-0">
          <FolderPlus className="size-4" aria-hidden />
          Nowy folder
        </Button>
      </div>

      {foldersQ.isError ? (
        <p role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-[12.5px] text-destructive">
          Nie udało się wczytać folderów — pliki z folderów są pod swoim rodzajem.
        </p>
      ) : null}
      {ordersQ.isError && httpStatus(ordersQ.error) !== 403 ? (
        <p role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-[12.5px] text-destructive">
          Nie udało się wczytać PDF-ów z zakładki Zamówienia — lista zamówień może być niepełna.
        </p>
      ) : null}

      {docsQ.isLoading ? (
        <p className="text-sm text-muted-foreground">Ładowanie dokumentów…</p>
      ) : docsQ.isError ? (
        <QueryStateNotice state="error" description="Nie udało się wczytać dokumentów kontraktu." onRetry={() => void docsQ.refetch()} />
      ) : docsQ.isSuccess && rows.length === 0 ? (
        <p className="rounded-xl border border-border bg-card px-4 py-5 text-[13px] text-muted-foreground shadow-xs">
          Kontrakt nie ma jeszcze dokumentów — przeciągnij podpisaną umowę na pole wyżej.
        </p>
      ) : (
        <div className="overflow-hidden rounded-xl border border-border bg-card shadow-xs">
          <table className="w-full table-fixed">
            <colgroup>
              <col />
              <col className="w-[112px]" />
              <col className="w-[124px]" />
              <col className="w-[76px]" />
            </colgroup>
            <thead>
              <tr className="border-b border-border text-left">
                <th scope="col" className={cn(CALM_HEAD, "py-2 pl-3.5 pr-3")}>
                  Nazwa
                </th>
                <th scope="col" className={cn(CALM_HEAD, "py-2 pr-3")}>
                  Rodzaj
                </th>
                <th scope="col" className={cn(CALM_HEAD, "py-2 pr-3")}>
                  Data dokumentu
                </th>
                <th scope="col" className="py-2 pr-2">
                  <span className="sr-only">Akcje</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => {
                const date = docDateLabel(r);
                const folder = r.folderId != null ? folderName.get(r.folderId) : undefined;
                return (
                  <tr key={r.key} className={cn(CALM_ROW, "group h-10 last:border-b-0 hover:bg-muted/30")}>
                    <td className="py-2 pl-3.5 pr-3">
                      <div className="flex min-w-0 items-center gap-2">
                        <DocIcon group={r.group} />
                        <button
                          type="button"
                          title={[r.name, r.note, addedLine(r), fmtSize(r.sizeBytes)].filter(Boolean).join("\n")}
                          className="min-w-0 truncate text-left text-[13px] leading-6 text-foreground hover:text-primary hover:underline"
                        >
                          {r.name}
                        </button>
                      </div>
                    </td>
                    <td className="py-2 pr-3 text-[12.5px] leading-6 text-foreground">
                      <span
                        className="inline-flex max-w-full items-center gap-1"
                        title={
                          folder
                            ? `W folderze „${folder}”`
                            : r.kindFromName
                              ? "Rodzaj rozpoznany z nazwy pliku — w bazie plik ma typ „Inne”."
                              : undefined
                        }
                      >
                        {folder && filter === "all" ? (
                          <Folder className="size-3.5 shrink-0 text-muted-foreground" aria-label={`w folderze ${folder}`} />
                        ) : null}
                        <span className="truncate">{r.kindLabel}</span>
                      </span>
                    </td>
                    <td className="whitespace-nowrap py-2 pr-3 text-[12.5px] leading-6 tabular-nums">
                      {date ? (
                        <span className="text-foreground">{date}</span>
                      ) : r.origin !== "import" ? (
                        <span className="text-muted-foreground">dodano {fmtDate(r.addedDay)}</span>
                      ) : (
                        <span className={CALM_EMPTY}>—</span>
                      )}
                    </td>
                    <td className="py-1 pr-2">
                      <DocRowActions name={r.name} movable={r.group !== "zamowienia"} />
                    </td>
                  </tr>
                );
              })}
              {visible.length === 0 ? (
                <tr className="h-10">
                  <td colSpan={4} className="px-3.5 py-3 text-[13px] text-muted-foreground">
                    Pusty folder — przenieś do niego pliki z menu „⋯” przy pliku.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}
      {batch ? <p className="text-[12px] text-muted-foreground">{batchSentence(batch)}.</p> : null}
    </div>
  );
}
