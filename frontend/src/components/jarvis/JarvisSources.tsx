"use client";

/**
 * Źródła odpowiedzi — dwie osobne grupy:
 *
 * - „Źródła z NEXUSA”: dokumenty, z których czytały narzędzia tej tury
 *   (podpisana umowa kontraktu, umowa ramowa klienta). Adres buduje backend
 *   z identyfikatorów w wyniku narzędzia, nigdy z tekstu modelu; tu
 *   przyjmujemy wyłącznie ścieżkę tej aplikacji („/…”, bez „//”).
 * - „Źródła z internetu”: JEDYNE miejsce, gdzie Jarvis pokazuje linki
 *   zewnętrzne. Adresy pochodzą z wyników wyszukiwarki, tylko http(s),
 *   otwierają się w nowej karcie po kliknięciu człowieka.
 */

import Link from "next/link";
import { ExternalLink, FileText, Globe } from "lucide-react";
import type { JarvisSource } from "@/lib/jarvis/types";

export function isHttpUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:";
  } catch {
    return false;
  }
}

/** Ścieżka NEXUSA: jeden „/” na początku, bez schematu, hosta i ukośnika wstecznego. */
export function isNexusPath(url: string): boolean {
  return /^\/(?![/\\])[A-Za-z0-9\-._~/?=&%]*$/.test(url);
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

const NEXUS_KIND_LABEL: Record<NonNullable<JarvisSource["kind"]>, string> = {
  contract_document: "Dokumenty kontraktu",
  framework_contract: "Umowy ramowe klienta",
};

function GroupTitle({ icon: Icon, children }: { icon: typeof Globe; children: string }) {
  return (
    <p className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {children}
    </p>
  );
}

export function JarvisSources({
  items,
  onNavigate,
}: {
  items: JarvisSource[];
  onNavigate?: () => void;
}) {
  const nexus = items.filter((i) => i.origin === "nexus" && isNexusPath(i.url));
  const web = items.filter((i) => i.origin !== "nexus" && isHttpUrl(i.url));
  if (nexus.length === 0 && web.length === 0) return null;
  return (
    <div className="space-y-2 rounded-lg border border-border bg-muted/40 px-3 py-2" data-testid="jarvis-sources">
      {nexus.length > 0 && (
        <section data-testid="jarvis-sources-nexus">
          <GroupTitle icon={FileText}>Źródła z NEXUSA</GroupTitle>
          <ol className="space-y-1">
            {nexus.map((source, index) => (
              <li key={`${source.url}|${source.title}`} className="text-xs">
                <Link
                  href={source.url}
                  onClick={onNavigate}
                  className="inline-flex items-start gap-1 text-primary hover:underline"
                >
                  <span className="text-muted-foreground">{index + 1}.</span>
                  <span className="line-clamp-2">{source.title}</span>
                </Link>
                {source.kind && (
                  <span className="ml-4 block text-[11px] text-muted-foreground">{NEXUS_KIND_LABEL[source.kind]}</span>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}
      {web.length > 0 && (
        <section data-testid="jarvis-sources-web">
          <GroupTitle icon={Globe}>Źródła z internetu</GroupTitle>
          <ol className="space-y-1">
            {web.map((source, index) => (
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
        </section>
      )}
    </div>
  );
}
