"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

const SEGMENT_LABELS: Record<string, string> = {
  "": "Dashboard",
  candidates: "Kandydaci",
  jobs: "Oferty pracy",
  clients: "Klienci",
  contacts: "Kontakty",
  contracts: "Kontrakty",
  talents: "Talenty",
  analytics: "Analityka",
  reports: "Raporty",
  calendar: "Kalendarz",
  settings: "Ustawienia",
  templates: "Szablony email",
  admin: "Admin",
  profile: "Profil",
  diagnostics: "Diagnostyka",
  v2: "UI Showcase",
  pipeline: "Pipeline",
  scoring: "Scoring",
  "pipeline-templates": "Procesy",
  "contract-templates": "Szablony kontraktów",
  compare: "Porównanie",
  manager: "Panel managera",
};

const ENTITY_NAME_FETCHERS: Record<string, (id: string) => Promise<string>> = {
  candidates: async (id) => {
    const r = await api.get(`/api/candidates/${id}`);
    return `${r.data.name ?? ""} ${r.data.lastname ?? ""}`.trim() || id;
  },
  jobs: async (id) => {
    const r = await api.get(`/api/jobs/${id}`);
    return r.data.title ?? id;
  },
  clients: async (id) => {
    const r = await api.get(`/api/clients/${id}`);
    return r.data.name ?? id;
  },
};

function isNumeric(s: string) {
  return /^\d+$/.test(s);
}

function DynamicLabel({ entityType, id }: { entityType: string; id: string }) {
  const fetcher = ENTITY_NAME_FETCHERS[entityType];
  const { data: label, isLoading } = useQuery({
    queryKey: ["breadcrumb-v2", entityType, id],
    queryFn: () => fetcher(id),
    enabled: !!fetcher,
    staleTime: 60_000,
  });
  if (!fetcher) return <span>{id}</span>;
  if (isLoading) return <span className="opacity-50">…</span>;
  return <span>{label ?? id}</span>;
}

export function BreadcrumbV2({ className }: { className?: string }) {
  const pathname = usePathname();
  const segments = pathname.split("/").filter(Boolean);

  if (segments.length === 0) {
    return (
      <span className={cn("text-sm font-medium text-[hsl(var(--text-title))]", className)}>
        Dashboard
      </span>
    );
  }

  const crumbs: { label: React.ReactNode; href: string }[] = [{ label: "Dashboard", href: "/" }];

  let path = "";
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    path += "/" + seg;
    const prevSeg = segments[i - 1];
    if (isNumeric(seg) && prevSeg && ENTITY_NAME_FETCHERS[prevSeg]) {
      crumbs.push({
        label: <DynamicLabel entityType={prevSeg} id={seg} />,
        href: path,
      });
    } else if (!isNumeric(seg)) {
      const label = SEGMENT_LABELS[seg] ?? (seg.length > 14 ? seg.slice(0, 12) + "…" : seg);
      crumbs.push({ label, href: path });
    }
  }

  return (
    <nav
      aria-label="Ścieżka"
      className={cn("flex items-center gap-1 text-sm min-w-0", className)}
    >
      {crumbs.map((c, i) => {
        const isLast = i === crumbs.length - 1;
        return (
          <div key={c.href} className="flex items-center gap-1 min-w-0">
            {i > 0 && (
              <ChevronRight className="h-3 w-3 text-[hsl(var(--text-muted))] shrink-0" />
            )}
            {isLast ? (
              <span className="font-medium text-[hsl(var(--text-title))] truncate">
                {c.label}
              </span>
            ) : (
              <Link
                href={c.href}
                className="text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent))] truncate transition-colors"
              >
                {c.label}
              </Link>
            )}
          </div>
        );
      })}
    </nav>
  );
}
