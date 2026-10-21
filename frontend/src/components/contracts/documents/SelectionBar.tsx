"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { filesLabel, type DocumentFolder } from "@/lib/contract-document-folders";

const CURRENT = "current";

interface Props {
  count: number;
  folders: DocumentFolder[];
  pending: boolean;
  onMove: (folderId: number | null) => void;
  onNewFolder: () => void;
  onCancel: () => void;
}

/** Pasek nad listą po zaznaczeniu plików: „Przenieś do”, „Nowy folder z zaznaczonych”. */
export function SelectionBar({ count, folders, pending, onMove, onNewFolder, onCancel }: Props) {
  const [target, setTarget] = useState("");

  return (
    <div
      role="region"
      aria-label="Akcje dla zaznaczonych plików"
      className="mx-4 mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-sm"
    >
      <span className="font-semibold">Zaznaczono {filesLabel(count)}</span>
      <label htmlFor="move-target" className="ml-2 text-muted-foreground">
        Przenieś do
      </label>
      <select
        id="move-target"
        value={target}
        onChange={(e) => setTarget(e.target.value)}
        className="h-8 min-w-[14rem] rounded-md border border-border bg-card px-2 text-sm"
      >
        <option value="" disabled>
          Wybierz folder…
        </option>
        {folders.map((f) => (
          <option key={f.id} value={String(f.id)}>
            {f.name}
          </option>
        ))}
        <option value={CURRENT}>Aktualna umowa (bez folderu)</option>
      </select>
      <Button
        size="sm"
        disabled={!target}
        loading={pending}
        onClick={() => onMove(target === CURRENT ? null : Number(target))}
      >
        Przenieś
      </Button>
      <Button size="sm" variant="outline" onClick={onNewFolder}>
        Nowy folder z zaznaczonych
      </Button>
      <span className="flex-1" />
      <Button size="sm" variant="ghost" onClick={onCancel}>
        Anuluj
      </Button>
    </div>
  );
}
