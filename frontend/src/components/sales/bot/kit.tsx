"use client";

import { Bot, ExternalLink } from "lucide-react";
import type { ReactNode } from "react";

import { safeHref } from "@/components/sales/format";
import { cn } from "@/lib/utils";

/** Znacznik części karty, którą przygotował bot researchu. */
export function BotTag({ children = "Bot" }: { children?: ReactNode }) {
  return (
    <span className="inline-flex h-4 items-center gap-1 rounded bg-primary/10 px-1.5 text-[10px] font-medium uppercase tracking-[0.06em] text-primary">
      <Bot className="size-3" aria-hidden />
      {children}
    </span>
  );
}

/** Link do źródła z samą domeną; adres spoza http(s) nie renderuje się wcale. */
export function SourceLink({ url, className }: { url: string | null | undefined; className?: string }) {
  const href = safeHref(url);
  if (!href) return null;
  let host = href;
  try {
    host = new URL(href).hostname.replace(/^www\./, "");
  } catch {
    // zostaje pełny adres
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={cn("inline-flex items-center gap-0.5 text-xs text-primary hover:underline", className)}
    >
      {host}
      <ExternalLink className="size-3" aria-hidden />
    </a>
  );
}
