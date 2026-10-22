"use client";

/**
 * „Czeka na Twój podpis za B2B Network” nad pulpitem (podpis w NEXUSIE,
 * etap 1b, 21.10.2026). Jak „Do wysłania do klienta” — pas, nie kafelek:
 * zadanie ma dotrzeć do reprezentanta firmy, który pulpitu nie układał.
 * Widać go tylko wtedy, gdy kontraktor podpisał i umowa czeka na tę osobę;
 * podpis składa się w rejestrze (panel „Do podpisu za B2B Network”).
 */

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { FileSignature } from "lucide-react";

import { Button } from "@/components/ui/button";
import { hasActionAccess } from "@/lib/action-access";
import { ESIGN_MINE_KEY, b2bEsignApi, type EsignRequest } from "@/lib/api/b2bEsign";
import { formatDateTimePl } from "@/lib/date-pl";
import { useAuthStore } from "@/store/auth";

const REGISTER_HREF = "/contracts/b2b-generator";

function title(request: EsignRequest): string {
  const number = request.contract_number ?? `#${request.generated_contract_id}`;
  return `${number} · ${request.contractor_name}`;
}

export function EsignCompanyBand() {
  const user = useAuthStore((s) => s.user);
  const allowed = hasActionAccess(user, "b2b_contract_generator", "view");
  const mine = useQuery({
    queryKey: ESIGN_MINE_KEY,
    queryFn: b2bEsignApi.mine,
    staleTime: 60_000,
    enabled: allowed,
  });
  // Pas jest zadaniem, nie listą: bez umów czekających na tę osobę go nie ma.
  // Błąd zapytania też go chowa — ta sama lista stoi na górze rejestru.
  if (!allowed || !mine.isSuccess || mine.data.length === 0) return null;
  return (
    <section
      aria-label="Czeka na Twój podpis za B2B Network"
      className="overflow-hidden rounded-xl border border-primary/30 bg-card"
      data-testid="esign-company-band"
    >
      <div className="flex items-center justify-between gap-2 border-b border-border bg-primary/5 px-4 py-2.5">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <FileSignature className="h-4 w-4 text-primary" aria-hidden />
          Czeka na Twój podpis za B2B Network
        </h2>
        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
          {mine.data.length}
        </span>
      </div>
      <ul>
        {mine.data.map((request) => (
          <li
            key={request.id}
            className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-2 first:border-t-0"
          >
            <div className="min-w-0">
              <span className="block truncate text-sm font-medium text-foreground">
                {title(request)}
              </span>
              <span className="block text-xs text-muted-foreground">
                {request.client_name ? `${request.client_name} · ` : ""}
                kontraktor podpisał {formatDateTimePl(request.contractor_signed_at)}
              </span>
            </div>
            <Button asChild size="sm">
              <Link href={REGISTER_HREF}>Podpisz</Link>
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}
