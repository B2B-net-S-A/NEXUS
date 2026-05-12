"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Heart, Star } from "lucide-react";
import { api } from "@/lib/api";
import { useToast } from "@/components/Toast";

export type RelationshipStrength = "cold" | "warm" | "strong" | "champion";

interface ContactKeyFields {
  id: number;
  name: string;
  client_id: number;
  is_key_relationship: boolean;
  relationship_strength: RelationshipStrength | null;
  relationship_notes: string | null;
  last_personal_touchpoint_at: string | null;
}

interface KeyRelationshipDialogProps {
  contact: ContactKeyFields;
  onClose: () => void;
}

const STRENGTH_LABELS: Record<RelationshipStrength, string> = {
  cold: "🥶 Cold — wymiana maili biznesowych",
  warm: "🌤️ Warm — pamiętają nas, odpowiadają chętnie",
  strong: "🤝 Strong — spotkania osobiste, znamy się dobrze",
  champion: "⭐ Champion — wewnętrzny ambasador, poleca nas",
};

/** Modal edycji "kluczowej relacji" — flaga + siła + notatki + last touchpoint. */
export function KeyRelationshipDialog({
  contact,
  onClose,
}: KeyRelationshipDialogProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [isKey, setIsKey] = useState<boolean>(contact.is_key_relationship);
  const [strength, setStrength] = useState<RelationshipStrength | "">(
    contact.relationship_strength ?? "",
  );
  const [notes, setNotes] = useState<string>(contact.relationship_notes ?? "");
  const [touchpointDate, setTouchpointDate] = useState<string>(
    contact.last_personal_touchpoint_at
      ? contact.last_personal_touchpoint_at.slice(0, 10)
      : "",
  );

  const mutation = useMutation({
    mutationFn: () =>
      api.put(`/api/contacts/${contact.id}`, {
        is_key_relationship: isKey,
        relationship_strength: isKey ? (strength || null) : null,
        relationship_notes: notes || null,
        last_personal_touchpoint_at: touchpointDate
          ? new Date(touchpointDate).toISOString()
          : null,
      }),
    onSuccess: () => {
      showToast("Relacja zaktualizowana", "success");
      queryClient.invalidateQueries({
        queryKey: ["client-contacts", contact.client_id],
      });
      queryClient.invalidateQueries({ queryKey: ["my-relationships"] });
      onClose();
    },
    onError: (err: unknown) => {
      showToast(err instanceof Error ? err.message : "Błąd zapisu", "error");
    },
  });

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
        className="bg-card rounded-lg shadow-xl max-w-md w-full p-6 space-y-4 max-h-[90vh] overflow-auto"
      >
        <div className="flex items-center gap-2">
          <Heart className="w-5 h-5 text-pink-600" />
          <div>
            <h3 className="text-lg font-semibold">Relacja z {contact.name}</h3>
            <p className="text-xs text-muted-foreground">
              Twoja więź z tą osobą (niezależnie od jej pozycji w firmie).
            </p>
          </div>
        </div>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={isKey}
            onChange={(e) => setIsKey(e.target.checked)}
            className="w-4 h-4"
          />
          <Star
            className={
              "w-4 h-4 " +
              (isKey ? "text-yellow-500 fill-yellow-500" : "text-muted-foreground")
            }
          />
          <span className="text-sm font-medium">Kluczowa relacja</span>
        </label>

        {isKey && (
          <>
            <label>
              <span className="text-sm">Siła relacji</span>
              <select
                value={strength}
                onChange={(e) =>
                  setStrength(e.target.value as RelationshipStrength | "")
                }
                className="mt-1 w-full px-3 py-2 border border-border rounded bg-background text-sm"
              >
                <option value="">— wybierz —</option>
                {(Object.keys(STRENGTH_LABELS) as RelationshipStrength[]).map(
                  (s) => (
                    <option key={s} value={s}>
                      {STRENGTH_LABELS[s]}
                    </option>
                  ),
                )}
              </select>
            </label>

            <label>
              <span className="text-sm">
                Last personal touchpoint (kawa, spotkanie poza biznesem)
              </span>
              <input
                type="date"
                value={touchpointDate}
                onChange={(e) => setTouchpointDate(e.target.value)}
                className="mt-1 w-full px-3 py-2 border border-border rounded bg-background text-sm"
              />
              <span className="text-xs text-muted-foreground mt-0.5 block">
                Osobne od &quot;last_contacted_at&quot; (każdy biznesowy kontakt).
              </span>
            </label>
          </>
        )}

        <label className="block">
          <span className="text-sm">Notatki o relacji</span>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={6}
            placeholder="Birthday, hobbies, jak rozmawiać, ulubione miejsca, rodzina, gift preferences..."
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background text-sm"
          />
        </label>

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-2 text-sm border border-border rounded"
          >
            Anuluj
          </button>
          <button
            type="submit"
            disabled={mutation.isPending}
            className="px-3 py-2 text-sm bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50"
          >
            {mutation.isPending ? "Zapisywanie…" : "Zapisz"}
          </button>
        </div>
      </form>
    </div>
  );
}
