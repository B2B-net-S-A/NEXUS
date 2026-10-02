"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Crown, Heart, Star } from "lucide-react";
import { api } from "@/lib/api";
import { KeyRelationshipDialog } from "@/components/KeyRelationshipDialog";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CALM_EMPTY, CALM_HEAD, CALM_SUBLINE } from "@/lib/calm-table";
import {
  hasPermission,
  isDeliveryLeadGoverned,
  permissionLabel,
} from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

type RelationshipStrength = "cold" | "warm" | "strong" | "champion";

interface MyRelationshipRow {
  contact_id: number;
  name: string;
  position: string | null;
  email: string | null;
  phone: string | null;
  client_id: number;
  client_name: string;
  is_decision_maker: boolean;
  relationship_strength: RelationshipStrength | null;
  relationship_notes: string | null;
  last_personal_touchpoint_at: string | null;
  last_contacted_at: string | null;
  days_since_personal_touchpoint: number | null;
}

export const RELATIONSHIP_STRENGTH_COLORS: Record<RelationshipStrength, string> = {
  cold: "bg-muted text-muted-foreground",
  warm: "bg-warning-muted text-warning-muted-foreground",
  strong: "bg-primary/10 text-primary",
  champion: "bg-success-muted text-success-muted-foreground",
};

// Etykiety czyta też zakładka „Kontakty klienta” w profilu klienta.
export const RELATIONSHIP_STRENGTH_LABELS: Record<RelationshipStrength, string> = {
  cold: "Chłodna",
  warm: "Ciepła",
  strong: "Mocna",
  champion: "Champion",
};

/** Kropka przy „Ostatnim kontakcie”: im dawniej, tym pilniej. */
function touchpointTone(days: number): StatusDotTone {
  if (days > 90) return "danger";
  if (days > 30) return "warning";
  return "success";
}

/**
 * Kluczowe relacje z klientami — tryb „Kontakty" ekranu Klienci
 * (`/clients?view=contacts`). Do 22.09.2026 osobna pozycja menu
 * „Moje relacje" (`/my-relationships` przekierowuje tutaj).
 */
export function KeyRelationshipsPanel() {
  const user = useAuthStore((state) => state.user);
  const impersonating = useAuthStore((state) => state.realUser !== null);
  // Konto rządzone portfelem Delivery Leada dostaje z API wyłącznie relacje,
  // których samo jest właścicielem; każdy inny czytelnik Delivery — wszystkie
  // relacje w organizacji (`reads_delivery_organization_wide` w backendzie).
  const ownRelationships = isDeliveryLeadGoverned(user);
  // „Aktualizuj” zapisuje pola relacji kontaktu: wolno właścicielowi relacji
  // (czyli każdemu wierszowi listy „moich” relacji) albo posiadaczowi
  // „Klienci: dodawanie i edycja”. W podglądzie jako inny użytkownik — nikomu.
  const canEdit =
    !impersonating && (ownRelationships || hasPermission(user, "clients_edit"));
  const [editing, setEditing] = useState<MyRelationshipRow | null>(null);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["my-relationships"],
    queryFn: async () => {
      const res = await api.get<MyRelationshipRow[]>("/api/my-relationships");
      return res.data;
    },
  });

  if (isLoading) {
    return (
      <div className="py-6 text-muted-foreground">
        Ładowanie kluczowych relacji…
      </div>
    );
  }
  if (error) {
    // UAT A-B04: 403 (brak podglądu Delivery — np. w podglądzie jako
    // użytkownik) to odmowa, nie „Błąd ładowania. Czy jesteś zalogowany?".
    const state = resolveViewState({ isLoading: false, isError: true, error });
    return (
      <div>
        <QueryStateNotice
          state={state === "forbidden" ? "forbidden" : "error"}
          description={
            state === "forbidden"
              ? `Kluczowe relacje z klientami wymagają uprawnienia „${permissionLabel("delivery_view")}”. Poproś administratora o dostęp (Ustawienia → Zespół i dostęp → Osoby i role).`
              : "Nie udało się wczytać kluczowych relacji."
          }
          onRetry={() => refetch()}
        />
      </div>
    );
  }

  const rows = data ?? [];

  return (
    <div className="space-y-3">
      <header>
        <h2 className="font-display text-base font-semibold text-foreground">
          {ownRelationships ? "Moje kluczowe relacje" : "Kluczowe relacje w organizacji"}
        </h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {ownRelationships
            ? "Osoby u klientów, z którymi masz zbudowaną relację. "
            : "Wszystkie oznaczone relacje z klientami w organizacji. "}
          Oznaczasz je w profilu klienta: <strong>Kontakty klienta</strong> → ikona{" "}
          <Heart className="inline h-3 w-3 text-primary" aria-label="serca" /> →
          „Kluczowa relacja”. Najdawniej kontaktowane osoby są na górze.
        </p>
      </header>

      {rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-12 text-center text-sm text-muted-foreground">
          <Heart className="mx-auto mb-2 h-10 w-10 opacity-40" aria-hidden="true" />
          {ownRelationships
            ? "Nie masz jeszcze oznaczonych żadnych kluczowych relacji. Wejdź w profil klienta → Kontakty klienta, kliknij ikonę serca przy osobie i zaznacz „Kluczowa relacja”."
            : "W organizacji nie ma jeszcze oznaczonych kluczowych relacji."}
        </div>
      ) : (
        <Table density="compact" className="min-w-[900px]">
          <TableHeader>
            <TableRow>
              <TableHead className={CALM_HEAD}>Osoba</TableHead>
              <TableHead className={CALM_HEAD}>Klient</TableHead>
              <TableHead className={CALM_HEAD}>Siła relacji</TableHead>
              <TableHead className={CALM_HEAD}>Ostatni kontakt</TableHead>
              <TableHead className={CALM_HEAD}>Notatka</TableHead>
              {canEdit ? (
                <TableHead className={`${CALM_HEAD} text-right`}>Akcje</TableHead>
              ) : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.contact_id} className="h-[54px]">
                <TableCell>
                  <div className="flex min-w-0 items-center gap-1.5">
                    <Star
                      className="h-3.5 w-3.5 shrink-0 fill-warning text-warning"
                      aria-hidden="true"
                    />
                    <span className="font-medium text-foreground">{r.name}</span>
                    {r.is_decision_maker ? (
                      <Badge size="sm" variant="warning">
                        <Crown className="h-2.5 w-2.5" aria-hidden="true" />
                        Decydent
                      </Badge>
                    ) : null}
                  </div>
                  {r.position || r.email || r.phone ? (
                    <span className={`${CALM_SUBLINE} flex flex-wrap items-center gap-x-1.5`}>
                      {r.position ? <span>{r.position}</span> : null}
                      {r.email ? (
                        <>
                          {r.position ? <span aria-hidden="true">·</span> : null}
                          <a
                            href={`mailto:${r.email}`}
                            className="break-all hover:text-foreground hover:underline pointer-coarse:inline-flex pointer-coarse:min-h-10 pointer-coarse:items-center"
                          >
                            {r.email}
                          </a>
                        </>
                      ) : null}
                      {r.phone ? (
                        <>
                          {r.position || r.email ? <span aria-hidden="true">·</span> : null}
                          <a
                            href={`tel:${r.phone}`}
                            className="whitespace-nowrap tabular-nums hover:text-foreground hover:underline pointer-coarse:inline-flex pointer-coarse:min-h-10 pointer-coarse:items-center"
                          >
                            {r.phone}
                          </a>
                        </>
                      ) : null}
                    </span>
                  ) : null}
                </TableCell>
                <TableCell>
                  <Link
                    href={`/clients/${r.client_id}`}
                    className="font-medium text-primary hover:underline"
                  >
                    {r.client_name}
                  </Link>
                </TableCell>
                <TableCell>
                  {r.relationship_strength ? (
                    <span
                      className={`inline-flex whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium ${RELATIONSHIP_STRENGTH_COLORS[r.relationship_strength]}`}
                    >
                      {RELATIONSHIP_STRENGTH_LABELS[r.relationship_strength]}
                    </span>
                  ) : (
                    <span className={CALM_EMPTY}>—</span>
                  )}
                </TableCell>
                <TableCell>
                  {r.days_since_personal_touchpoint === null ? (
                    <StatusDot tone="neutral">Brak kontaktu</StatusDot>
                  ) : (
                    <StatusDot tone={touchpointTone(r.days_since_personal_touchpoint)}>
                      {r.days_since_personal_touchpoint} dni temu
                    </StatusDot>
                  )}
                </TableCell>
                <TableCell className="max-w-[340px] text-xs text-muted-foreground">
                  {r.relationship_notes ? (
                    <span className="line-clamp-2" title={r.relationship_notes}>
                      {r.relationship_notes}
                    </span>
                  ) : (
                    <span className={CALM_EMPTY}>—</span>
                  )}
                </TableCell>
                {canEdit ? (
                  <TableCell className="text-right">
                    <Button size="sm" variant="outline" onClick={() => setEditing(r)}>
                      Aktualizuj
                    </Button>
                  </TableCell>
                ) : null}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {canEdit && editing && (
        <KeyRelationshipDialog
          contact={{
            id: editing.contact_id,
            name: editing.name,
            client_id: editing.client_id,
            is_key_relationship: true,
            relationship_strength: editing.relationship_strength,
            relationship_notes: editing.relationship_notes,
            last_personal_touchpoint_at: editing.last_personal_touchpoint_at,
          }}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}
