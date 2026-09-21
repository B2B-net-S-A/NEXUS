"use client";

/**
 * Źródła odpowiedzi z internetu. JEDYNE miejsce, gdzie Jarvis pokazuje linki
 * zewnętrzne: adresy pochodzą z wyników wyszukiwarki (nie z tekstu modelu),
 * tylko http(s) (filtruje też backend), otwierają się w nowej karcie po
 * kliknięciu człowieka — nic nie jest pobierane automatycznie.
 */

import { ExternalLink, Globe } from "lucide-react";
import type { JarvisSource } from "@/lib/jarvis/types";

export function isHttpUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:";
  } catch {
    return false;
  }
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function JarvisSources({ items }: { items: JarvisSource[] }) {
  const safe = items.filter((i) => isHttpUrl(i.url));
  if (safe.length === 0) return null;
  return (
    <div className="rounded-lg border border-border bg-muted/40 px-3 py-2" data-testid="jarvis-sources">
      <p className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <Globe className="h-3.5 w-3.5" aria-hidden />
        Źródła z internetu
      </p>
      <ol className="space-y-1">
        {safe.map((source, index) => (
          <li key={source.url} className="text-xs">
            <a
              href={source.url}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="inline-flex items-start gap-1 text-primary hover:underline"
            >
              <span className="text-muted-foreground">{index + 1}.</span>
              <span className="line-clamp-1">{source.title || hostOf(source.url)}</span>
              <ExternalLink className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
            </a>
            <span className="ml-4 block text-[11px] text-muted-foreground">{hostOf(source.url)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
