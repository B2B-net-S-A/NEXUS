"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Mail,
  FileUp,
  Search,
  UserPlus,
  Megaphone,
  Users,
  Database,
} from "lucide-react";
import {
  candidateSourcesApi,
  type CandidateSourceEventDto,
  type SourceChannel,
} from "@/lib/api";
import { cn } from "@/lib/utils";

interface CandidateSourcesPanelProps {
  candidateId: number;
}

const CHANNEL_ICONS: Record<SourceChannel, React.ReactNode> = {
  manual: <UserPlus className="w-3.5 h-3.5" />,
  aktywny_search: <Search className="w-3.5 h-3.5" />,
  cv_upload: <FileUp className="w-3.5 h-3.5" />,
  email: <Mail className="w-3.5 h-3.5" />,
  posting: <Megaphone className="w-3.5 h-3.5" />,
  referral: <Users className="w-3.5 h-3.5" />,
  import_csv: <Database className="w-3.5 h-3.5" />,
};

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function utmTooltip(event: CandidateSourceEventDto): string | undefined {
  const parts: string[] = [];
  if (event.utm_source) parts.push(`source=${event.utm_source}`);
  if (event.utm_medium) parts.push(`medium=${event.utm_medium}`);
  if (event.utm_campaign) parts.push(`campaign=${event.utm_campaign}`);
  if (event.utm_term) parts.push(`term=${event.utm_term}`);
  if (event.utm_content) parts.push(`content=${event.utm_content}`);
  return parts.length > 0 ? parts.join(" · ") : undefined;
}

/**
 * Renders the multi-line "Źródła aplikacji" block on the candidate profile
 * sidebar (Traffit parity: their sidebar shows "Dodany manualnie • 08/05/2026
 * / E-mail • 09/05/2026"). Each row also surfaces UTM data via tooltip when
 * present.
 */
export function CandidateSourcesPanel({ candidateId }: CandidateSourcesPanelProps) {
  const { data, isLoading } = useQuery({
    queryKey: ["candidate-sources", candidateId],
    queryFn: () => candidateSourcesApi.list(candidateId).then((r) => r.data),
    staleTime: 60 * 1000,
  });

  if (isLoading) {
    return (
      <div className="text-xs text-muted-foreground italic">
        Ładowanie źródeł…
      </div>
    );
  }

  const events = data ?? [];

  if (events.length === 0) {
    return (
      <div className="text-xs text-muted-foreground italic">
        Brak zarejestrowanych źródeł aplikacji.
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
        Źródła aplikacji
      </h4>
      <ul className="space-y-1">
        {events.map((event) => {
          const tooltip = utmTooltip(event);
          const hasCampaign = Boolean(event.utm_campaign);
          return (
            <li
              key={event.id}
              className="flex items-center gap-2 text-sm text-foreground"
              title={tooltip}
            >
              <span
                className={cn(
                  "shrink-0 inline-flex items-center justify-center w-5 h-5 rounded text-muted-foreground",
                  hasCampaign && "text-primary",
                )}
              >
                {CHANNEL_ICONS[event.channel] ?? null}
              </span>
              <span className="truncate">
                {event.channel_label}
                <span className="text-muted-foreground/60">
                  {" "}
                  · {formatDate(event.captured_at)}
                </span>
                {hasCampaign && (
                  <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-primary/10 text-primary font-mono">
                    {event.utm_campaign}
                  </span>
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
