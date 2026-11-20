"use client";

import { ChevronDown, Folder, FolderPlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { filesLabel, type DocumentFolder } from "@/lib/contract-document-folders";

interface Props {
  count: number;
  folders: readonly DocumentFolder[];
  pending: boolean;
  onMove: (folderId: number | null) => void;
  onNewFolder: () => void;
  onCancel: () => void;
}

/**
 * Pasek nad tabelą po zaznaczeniu plików: „Przenieś do” (lista folderów
 * w menu, bez natywnego `<select>`), „Nowy folder z zaznaczonych”, „Anuluj”.
 * „Przenieś do” pojawia się, gdy jest dokąd przenieść — bez folderów zostaje
 * nowy folder z zaznaczonych.
 */
export function DocumentSelectionBar({ count, folders, pending, onMove, onNewFolder, onCancel }: Props) {
  return (
    <div
      role="region"
      aria-label="Akcje dla zaznaczonych plików"
      className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-[13px]"
    >
      <span className="font-semibold text-foreground">Zaznaczono {filesLabel(count)}</span>
      {folders.length > 0 && (
        <DropdownMenu modal={false}>
          <DropdownMenuTrigger asChild>
            <Button type="button" size="sm" variant="outline" loading={pending}>
              Przenieś do
              <ChevronDown className="size-3.5" aria-hidden="true" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="min-w-56">
            {folders.map((folder) => (
              <DropdownMenuItem key={folder.id} onSelect={() => onMove(folder.id)}>
                <Folder className="size-4 text-muted-foreground" aria-hidden="true" />
                {folder.name}
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => onMove(null)}>Aktualna umowa (bez folderu)</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      <Button type="button" size="sm" variant="outline" onClick={onNewFolder}>
        <FolderPlus className="size-4" aria-hidden="true" />
        Nowy folder z zaznaczonych
      </Button>
      <span className="flex-1" />
      <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
        Anuluj
      </Button>
    </div>
  );
}
