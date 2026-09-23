"use client";

/**
 * Markdown odpowiedzi Jarvisa — z dwiema świadomymi blokadami:
 *
 * - OBRAZKI SĄ WYŁĄCZONE. Model czyta niezaufane treści (CV, notatki). Obrazek
 *   z adresem zewnętrznym to kanał wycieku: przeglądarka sama pobrałaby URL
 *   z danymi doklejonymi przez wstrzyknięty prompt. Zostaje sam tekst alt.
 * - LINKI TYLKO WEWNĘTRZNE. Ścieżka względna (`/candidates/12`) idzie przez
 *   `next/link`; wszystko inne renderuje się jako zwykły tekst.
 *
 * Reszta konfiguracji jak w module Pomoc (`remark-gfm`, bez `rehype-raw`).
 */

import Link from "next/link";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { safeInternalPath } from "@/lib/safe-href";

export function isInternalHref(href: string | undefined): href is string {
  return safeInternalPath(href) !== null;
}

const COMPONENTS: Components = {
  img: ({ alt }) => (alt ? <span>{alt}</span> : null),
  a: ({ href, children }) =>
    isInternalHref(href) ? (
      <Link href={href} className="font-medium text-primary underline-offset-2 hover:underline">
        {children}
      </Link>
    ) : (
      <span>{children}</span>
    ),
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-xs">{children}</table>
    </div>
  ),
  th: ({ children }) => <th className="border-b border-border px-2 py-1 text-left font-semibold">{children}</th>,
  td: ({ children }) => <td className="border-b border-border/60 px-2 py-1 align-top">{children}</td>,
};

export function JarvisMarkdown({ children }: { children: string }) {
  return (
    <div className="prose prose-sm max-w-none text-foreground dark:prose-invert prose-p:my-1.5 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-headings:my-2 prose-strong:text-foreground">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
