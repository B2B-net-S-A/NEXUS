"use client";

/** Przycisk do ekranu NEXUSA — tak Jarvis obsługuje operacje, których nie wykonuje. */

import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import type { JarvisLink } from "@/lib/jarvis/types";
import { isInternalHref } from "./JarvisMarkdown";

export function JarvisDeepLinkCard({ link, onNavigate }: { link: JarvisLink; onNavigate?: () => void }) {
  if (!isInternalHref(link.href)) return null;
  return (
    <div className="rounded-lg border border-border bg-muted/50 p-3" data-testid="jarvis-link-card">
      {link.reason && <p className="mb-2 text-sm text-foreground">{link.reason}</p>}
      <Link
        href={link.href}
        onClick={onNavigate}
        className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
      >
        Otwórz: {link.label}
        <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
      </Link>
    </div>
  );
}
