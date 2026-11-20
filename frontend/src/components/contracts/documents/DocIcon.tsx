import { ClipboardList, FilePen, FileText, Folder, ScrollText } from "lucide-react";

import { cn } from "@/lib/utils";

import type { DocGroupKey } from "./document-groups";

const ICON = {
  umowy: ScrollText,
  aneksy: FilePen,
  zamowienia: ClipboardList,
  inne: FileText,
  folder: Folder,
} as const;

/** Ikona rodzaju pliku (grupy) albo folderu — ta sama w wierszu i w karcie „Obowiązuje teraz”. */
export function DocIcon({ group, className }: { group: DocGroupKey | "folder"; className?: string }) {
  const Icon = ICON[group];
  return <Icon className={cn("size-4 shrink-0 text-muted-foreground", className)} aria-hidden="true" />;
}
