"use client";

/**
 * „Klient coś zmienił” od Jarvisa (23.11.2026) — nic nie zostało zmienione.
 * „Pokaż i popraw” zostawia treść od klienta dla okna na stronie rekrutacji
 * (`stashClientChangeText`) i tam prowadzi; okno samo prosi o listę zmian.
 * Streszczenie to zwykły tekst od modelu — bez markdownu.
 */

import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

import { clientChangeHref, stashClientChangeText } from "@/lib/champion-client-change";
import type { JarvisClientChange } from "@/lib/jarvis/types";

interface JarvisClientChangeCardProps {
  proposal: JarvisClientChange;
  onNavigate?: () => void;
}

export function JarvisClientChangeCard({ proposal, onNavigate }: JarvisClientChangeCardProps) {
  const title = proposal.job_title?.trim() || `Rekrutacja #${proposal.job_id}`;
  return (
    <div className="rounded-lg border border-primary/30 bg-card p-3 shadow-xs" data-testid="jarvis-client-change">
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-primary">
        Zmiana od klienta — nic nie zmieniono
      </div>
      <p className="text-xs text-muted-foreground">
        Profil Championa: <span className="font-medium text-foreground">{title}</span>
      </p>
      {proposal.summary && (
        <p className="mt-1.5 whitespace-pre-wrap break-words text-sm text-foreground">{proposal.summary}</p>
      )}
      <p className="mt-1.5 text-xs text-muted-foreground">
        W oknie zobaczysz listę zmian w wymaganiach, opisie i pytaniach — odznaczysz albo poprawisz, zanim zapiszesz.
      </p>
      <Link
        href={clientChangeHref(proposal.job_id)}
        onClick={() => {
          stashClientChangeText(proposal.job_id, proposal.text);
          onNavigate?.();
        }}
        className="mt-2.5 inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
      >
        Pokaż i popraw
        <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
      </Link>
    </div>
  );
}
