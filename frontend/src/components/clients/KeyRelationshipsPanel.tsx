"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  AlertCircle,
  Building2,
  Crown,
  Heart,
  Mail,
  Phone,
  Star,
} from "lucide-react";
import { api } from "@/lib/api";
import { KeyRelationshipDialog } from "@/components/KeyRelationshipDialog";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { resolveViewState } from "@/lib/view-state";
import { hasRole, useAuthStore } from "@/store/auth";

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

const STRENGTH_COLORS: Record<RelationshipStrength, string> = {
  cold: "bg-blue-50 text-blue-700",
  warm: "bg-yellow-50 text-yellow-700",
  strong: "bg-green-50 text-green-700",
  champion: "bg-violet-100 text-violet-800",
};

const STRENGTH_LABELS: Record<RelationshipStrength, string> = {
  cold: "🥶 Cold",
  warm: "🌤️ Warm",
  strong: "🤝 Strong",
  champion: "⭐ Champion",
};

/**
 * Kluczowe relacje z klientami — tryb „Kontakty" ekranu Klienci
 * (`/clients?view=contacts`). Do 22.09.2026 osobna pozycja menu
 * „Moje relacje" (`/my-relationships` przekierowuje tutaj).
 */
export function KeyRelationshipsPanel() {
  const user = useAuthStore((state) => state.user);
  const isFinance = hasRole(user, "finance");
  const canEdit = hasRole(
    user,
    "admin",
    "head_of_recruitment",
    "delivery_lead",
    "tac",
  );
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
    // UAT A-B04: 403 (brak sekcji — np. w podglądzie jako użytkownik) to
    // odmowa, nie „Błąd ładowania. Czy jesteś zalogowany?".
    const state = resolveViewState({ isLoading: false, isError: true, error });
    return (
      <div>
        <QueryStateNotice
          state={state === "forbidden" ? "forbidden" : "error"}
          description={
            state === "forbidden"
              ? "Kluczowe relacje z klientami nie są dostępne dla Twojej roli."
              : "Nie udało się wczytać kluczowych relacji."
          }
          onRetry={() => refetch()}
        />
      </div>
    );
  }

  const rows = data ?? [];

  return (
    <div className="space-y-4">
      <header>
        <h2 className="text-xl font-bold flex items-center gap-2">
          <Heart className="w-6 h-6 text-pink-600" />
          {isFinance ? "Kluczowe relacje w organizacji" : "Moje kluczowe relacje"}
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          {isFinance
            ? "Wszystkie oznaczone relacje z klientami w organizacji. "
            : "Osoby u klientów, z którymi DL/TAC ma zbudowaną relację. "}
          Oznaczasz je w profilu klienta: <strong>Kontakty klienta</strong> → ikona{" "}
          <Heart className="w-3 h-3 inline text-pink-600" aria-label="serca" /> →
          „Kluczowa relacja”. Oznaczony kontakt dostaje{" "}
          <Star className="w-3 h-3 inline text-yellow-500 fill-yellow-500" aria-label="gwiazdkę" />.
          Sortowanie: najpilniejsze (najstarszy personal touchpoint) na górze.
        </p>
      </header>

      {rows.length === 0 ? (
        <div className="border border-dashed border-border rounded-lg p-12 text-center text-muted-foreground">
          <Heart className="w-12 h-12 mx-auto mb-2 opacity-40" />
          {isFinance
            ? "W organizacji nie ma jeszcze oznaczonych kluczowych relacji."
            : "Nie masz jeszcze oznaczonych żadnych kluczowych relacji. Wejdź w profil klienta → Kontakty klienta, kliknij ikonę serca przy osobie i zaznacz „Kluczowa relacja”."}
        </div>
      ) : (
        <ul className="space-y-3">
          {rows.map((r) => (
            <li
              key={r.contact_id}
              className="border border-border rounded-lg p-4 bg-card hover:bg-accent/30 transition-colors"
            >
              <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Star className="w-4 h-4 text-yellow-500 fill-yellow-500" />
                    <h3 className="font-semibold">{r.name}</h3>
                    {r.relationship_strength && (
                      <span
                        className={`text-xs px-2 py-0.5 rounded ${STRENGTH_COLORS[r.relationship_strength]}`}
                      >
                        {STRENGTH_LABELS[r.relationship_strength]}
                      </span>
                    )}
                    {r.is_decision_maker && (
                      <span className="flex items-center gap-0.5 px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded text-xs font-semibold">
                        <Crown className="w-3 h-3" />
                        Decydent
                      </span>
                    )}
                  </div>
                  <div className="text-sm text-muted-foreground mt-1">
                    {r.position && <span>{r.position}</span>}
                    {r.position && " · "}
                    <Link
                      href={`/clients/${r.client_id}`}
                      className="hover:text-violet-600 inline-flex items-center gap-1"
                    >
                      <Building2 className="w-3 h-3" />
                      {r.client_name}
                    </Link>
                  </div>
                  <div className="flex flex-wrap gap-3 mt-2 text-xs">
                    {r.email && (
                      <a
                        href={`mailto:${r.email}`}
                        className="flex min-w-0 max-w-full items-center gap-1 text-primary hover:underline pointer-coarse:min-h-10"
                      >
                        <Mail className="w-3 h-3 shrink-0" />
                        <span className="break-all">{r.email}</span>
                      </a>
                    )}
                    {r.phone && (
                      <a
                        href={`tel:${r.phone}`}
                        className="flex items-center gap-1 text-muted-foreground hover:text-foreground pointer-coarse:min-h-10"
                      >
                        <Phone className="w-3 h-3" />
                        {r.phone}
                      </a>
                    )}
                  </div>
                  {r.relationship_notes && (
                    <p className="mt-2 text-xs text-pink-700 italic border-l-2 border-pink-200 pl-2">
                      {r.relationship_notes}
                    </p>
                  )}
                </div>
                <div className="flex flex-col items-end gap-2 shrink-0">
                  {r.days_since_personal_touchpoint === null ? (
                    <span className="text-xs text-orange-700 bg-orange-50 px-2 py-1 rounded flex items-center gap-1">
                      <AlertCircle className="w-3 h-3" />
                      Brak personal touchpoint
                    </span>
                  ) : (
                    <span
                      className={
                        "text-xs px-2 py-1 rounded " +
                        (r.days_since_personal_touchpoint > 90
                          ? "bg-red-50 text-red-700"
                          : r.days_since_personal_touchpoint > 30
                          ? "bg-yellow-50 text-yellow-700"
                          : "bg-green-50 text-green-700")
                      }
                    >
                      {r.days_since_personal_touchpoint} dni temu
                    </span>
                  )}
                  {canEdit && (
                    <button
                      onClick={() => setEditing(r)}
                      className="text-xs text-violet-600 hover:text-violet-700 underline"
                    >
                      Aktualizuj
                    </button>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
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
