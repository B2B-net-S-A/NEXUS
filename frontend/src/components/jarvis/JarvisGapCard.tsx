"use client";

/** „Tego nie zrobię” — czego Jarvisowi brakuje, co zrobić teraz i zgłoszenie potrzeby. */

import { useState } from "react";
import { Check, Lock, PackageOpen, Wrench } from "lucide-react";
import { reportJarvisGap } from "@/lib/jarvis/api";
import type { GapKind, JarvisGap } from "@/lib/jarvis/types";
import { apiErrorMessage } from "@/lib/api-error";

const KIND: Record<GapKind, { title: string; Icon: typeof Lock }> = {
  no_access: { title: "Twoja rola tego nie widzi", Icon: Lock },
  not_supported: { title: "Jeszcze tego nie umiem", Icon: Wrench },
  no_data: { title: "NEXUS tego nie przechowuje", Icon: PackageOpen },
};

export function JarvisGapCard({ gap }: { gap: JarvisGap }) {
  const [reported, setReported] = useState(gap.reported);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { title, Icon } = KIND[gap.kind] ?? KIND.not_supported;

  async function report() {
    setBusy(true);
    setError(null);
    try {
      await reportJarvisGap(gap.id);
      setReported(true);
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się zgłosić. Spróbuj jeszcze raz."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-warning/40 bg-warning-muted/40 p-3 text-sm" data-testid="jarvis-gap-card">
      <p className="flex items-center gap-1.5 font-semibold text-foreground">
        <Icon className="h-4 w-4 shrink-0 text-warning-muted-foreground" aria-hidden />
        {title}
      </p>
      {gap.need && <p className="mt-1 text-xs text-muted-foreground">Prośba: {gap.need}</p>}
      <dl className="mt-2 space-y-1.5">
        <div>
          <dt className="text-xs font-medium text-muted-foreground">Dlaczego</dt>
          <dd className="text-foreground">{gap.why}</dd>
        </div>
        {gap.workaround && (
          <div>
            <dt className="text-xs font-medium text-muted-foreground">Co możesz zrobić teraz</dt>
            <dd className="text-foreground">{gap.workaround}</dd>
          </div>
        )}
      </dl>
      <div className="mt-2.5">
        {reported ? (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-success-muted-foreground">
            <Check className="h-3.5 w-3.5" aria-hidden />
            Zgłoszone — trafi na listę „Czego Jarvis nie umie”
          </span>
        ) : (
          <button
            type="button"
            disabled={busy}
            onClick={report}
            className="rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground hover:bg-muted disabled:opacity-50"
          >
            Zgłoś, że tego potrzebuję
          </button>
        )}
        {error && (
          <p role="alert" className="mt-1.5 text-xs text-destructive">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
