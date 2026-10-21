"use client";

import { useEffect, useState } from "react";

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
import { filesLabel, pluralForm } from "@/lib/contract-document-folders";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Nazwy plików, które trafią do folderu (puste = pusty folder). */
  fileNames: string[];
  suggestions: string[];
  pending: boolean;
  error: string;
  onSubmit: (name: string) => void;
}

/** „Nowy folder” i „Nowy folder z zaznaczonych” — pole nazwy i podpowiedzi. */
export function NewFolderDialog({
  open,
  onOpenChange,
  fileNames,
  suggestions,
  pending,
  error,
  onSubmit,
}: Props) {
  const [name, setName] = useState("");

  useEffect(() => {
    if (open) setName(fileNames.length > 0 ? (suggestions[0] ?? "") : "");
  }, [open, fileNames.length, suggestions]);

  const count = fileNames.length;
  const trimmed = name.trim();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md">
        <DialogHeader>
          <DialogTitle>{count > 0 ? "Nowy folder z zaznaczonych" : "Nowy folder"}</DialogTitle>
          <DialogDescription>
            {count > 0
              ? `${filesLabel(count)} ${pluralForm(count, "trafi", "trafią", "trafi")} do nowego folderu. Pliki się nie zmieniają — zmienia się tylko miejsce na liście.`
              : "Folder pojawi się w sekcji „Foldery”. Pliki przeniesiesz do niego, zaznaczając je na liście."}
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (trimmed) onSubmit(trimmed);
          }}
        >
          <DialogBody className="space-y-4">
            <div>
              <label htmlFor="new-folder-name" className="mb-1.5 block text-sm font-medium">
                Nazwa folderu
              </label>
              <input
                id="new-folder-name"
                value={name}
                maxLength={120}
                autoFocus
                onChange={(e) => setName(e.target.value)}
                className="h-10 w-full rounded-md border border-border bg-card px-3 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>
            {suggestions.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Podpowiedzi
                </p>
                <div className="flex flex-wrap gap-2">
                  {suggestions.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setName(s)}
                      aria-pressed={trimmed === s}
                      className={cn(
                        "h-8 rounded-full border px-3 text-sm",
                        trimmed === s
                          ? "border-primary bg-primary/10 font-medium text-primary"
                          : "border-border bg-card hover:bg-muted",
                      )}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {count > 0 && (
              <ul
                aria-label="Pliki do przeniesienia"
                className="max-h-40 overflow-y-auto rounded-md border border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground"
              >
                {fileNames.map((f) => (
                  <li key={f} className="truncate py-0.5">
                    {f}
                  </li>
                ))}
              </ul>
            )}
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Anuluj
            </Button>
            <Button type="submit" loading={pending} disabled={!trimmed}>
              {count > 0 ? `Utwórz folder i przenieś ${filesLabel(count)}` : "Utwórz folder"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
