"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Crown, Plus, Trash2, UserCircle2 } from "lucide-react";
import api from "@/lib/api";
import { useToast } from "@/components/Toast";
import { useAuthStore } from "@/store/auth";

interface AssignmentUser {
  id: number;
  user_id: number;
  name: string;
  email: string;
  role?: string | null;
  created_at: string;
}

interface TacAssignment extends AssignmentUser {
  is_primary: boolean;
}

interface DlAssignment extends AssignmentUser {
  is_head: boolean;
}

interface ClientTeamResponse {
  tacs: TacAssignment[];
  delivery_leads: DlAssignment[];
}

interface AppUser {
  id: number;
  name?: string | null;
  full_name?: string | null;
  email: string;
  role?: string | null;
  is_active?: boolean;
}

const TAC_ROLES = ["tac", "delivery_lead", "admin", "head_of_recruitment"];
const DL_ROLES = ["delivery_lead", "admin", "head_of_recruitment"];

export function OwnersTab({ clientId }: { clientId: number }) {
  const qc = useQueryClient();
  const toast = useToast();
  const me = useAuthStore((s) => s.user);
  const canEdit =
    me?.role === "admin" || me?.role === "head_of_recruitment";

  const { data: team, isLoading } = useQuery<ClientTeamResponse>({
    queryKey: ["client-team", clientId],
    queryFn: () => api.get(`/api/clients/${clientId}/team`).then((r) => r.data),
  });

  const { data: allUsers } = useQuery<AppUser[]>({
    queryKey: ["users-list-owners"],
    queryFn: () => api.get<AppUser[]>("/api/users").then((r) => r.data),
    enabled: canEdit,
  });

  const [addingTac, setAddingTac] = useState(false);
  const [addingDl, setAddingDl] = useState(false);
  const [tacUserId, setTacUserId] = useState("");
  const [tacIsPrimary, setTacIsPrimary] = useState(false);
  const [dlUserId, setDlUserId] = useState("");
  const [dlIsHead, setDlIsHead] = useState(false);

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["client-team", clientId] });

  const addTac = useMutation({
    mutationFn: (body: { user_id: number; is_primary: boolean }) =>
      api.post(`/api/clients/${clientId}/tacs`, body),
    onSuccess: () => {
      toast.showSuccess("TAC dodany");
      setAddingTac(false);
      setTacUserId("");
      setTacIsPrimary(false);
      invalidate();
    },
    onError: (e: any) =>
      toast.showError(e?.response?.data?.detail || "Błąd dodawania TAC"),
  });

  const removeTac = useMutation({
    mutationFn: (userId: number) =>
      api.delete(`/api/clients/${clientId}/tacs/${userId}`),
    onSuccess: () => {
      toast.showSuccess("TAC usunięty");
      invalidate();
    },
  });

  const togglePrimaryTac = useMutation({
    mutationFn: (userId: number) =>
      api.put(`/api/clients/${clientId}/tacs/${userId}/toggle-primary`),
    onSuccess: () => {
      toast.showSuccess("Primary TAC zmieniony");
      invalidate();
    },
  });

  const addDl = useMutation({
    mutationFn: (body: {
      delivery_lead_user_id: number;
      client_id: number;
      is_head: boolean;
    }) => api.post(`/api/team-structure/dl-clients`, body),
    onSuccess: () => {
      toast.showSuccess("Delivery Lead dodany");
      setAddingDl(false);
      setDlUserId("");
      setDlIsHead(false);
      invalidate();
    },
    onError: (e: any) =>
      toast.showError(e?.response?.data?.detail || "Błąd dodawania DL"),
  });

  const removeDl = useMutation({
    mutationFn: (assignmentId: number) =>
      api.delete(`/api/team-structure/dl-clients/${assignmentId}`),
    onSuccess: () => {
      toast.showSuccess("DL usunięty");
      invalidate();
    },
  });

  const toggleHeadDl = useMutation({
    mutationFn: (assignmentId: number) =>
      api.put(`/api/team-structure/dl-clients/${assignmentId}/toggle-head`),
    onSuccess: () => {
      toast.showSuccess("Head DL zmieniony");
      invalidate();
    },
  });

  if (isLoading) {
    return (
      <div className="p-6 text-muted-foreground text-sm">Ładowanie opiekunów…</div>
    );
  }

  const tacs = team?.tacs ?? [];
  const dls = team?.delivery_leads ?? [];

  const tacCandidates =
    allUsers?.filter(
      (u) =>
        (u.is_active ?? true) &&
        TAC_ROLES.includes(u.role ?? "") &&
        !tacs.some((t) => t.user_id === u.id),
    ) ?? [];
  const dlCandidates =
    allUsers?.filter(
      (u) =>
        (u.is_active ?? true) &&
        DL_ROLES.includes(u.role ?? "") &&
        !dls.some((d) => d.user_id === u.id),
    ) ?? [];

  const userLabel = (u: AppUser) =>
    u.name || u.full_name || u.email;

  return (
    <div className="space-y-6">
      {!canEdit && (
        <div className="text-xs text-muted-foreground bg-muted dark:bg-card/40 rounded-lg px-3 py-2">
          Widok tylko do odczytu. Edycja opiekunów klienta wymaga roli
          <strong> admin</strong> lub <strong>head_of_recruitment</strong>.
        </div>
      )}

      {/* ── TAC ──────────────────────────────────────────────────────── */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-foreground dark:text-foreground">
            TAC (Talent Acquisition Consultants)
          </h3>
          {canEdit && !addingTac && (
            <button
              onClick={() => setAddingTac(true)}
              className="inline-flex items-center gap-1 text-xs px-3 py-1.5 bg-purple-600 text-white rounded-lg hover:bg-purple-700"
            >
              <Plus className="w-3.5 h-3.5" /> Dodaj TAC
            </button>
          )}
        </div>

        {addingTac && canEdit && (
          <div className="bg-muted dark:bg-card/40 rounded-lg p-4 mb-3 space-y-3">
            <label className="block text-xs text-muted-foreground">Użytkownik</label>
            <select
              className="w-full border border-border dark:border-border rounded-lg px-3 py-2 text-sm bg-card dark:bg-muted"
              value={tacUserId}
              onChange={(e) => setTacUserId(e.target.value)}
            >
              <option value="">— wybierz —</option>
              {tacCandidates.map((u) => (
                <option key={u.id} value={u.id}>
                  {userLabel(u)} ({u.role})
                </option>
              ))}
            </select>
            <label className="flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={tacIsPrimary}
                onChange={(e) => setTacIsPrimary(e.target.checked)}
              />
              Ustaw jako primary (główny opiekun klienta)
            </label>
            <div className="flex gap-2">
              <button
                disabled={!tacUserId || addTac.isPending}
                onClick={() =>
                  addTac.mutate({
                    user_id: Number(tacUserId),
                    is_primary: tacIsPrimary,
                  })
                }
                className="text-xs px-3 py-1.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50"
              >
                Dodaj
              </button>
              <button
                onClick={() => {
                  setAddingTac(false);
                  setTacUserId("");
                  setTacIsPrimary(false);
                }}
                className="text-xs px-3 py-1.5 text-muted-foreground hover:text-foreground"
              >
                Anuluj
              </button>
            </div>
          </div>
        )}

        {tacs.length === 0 ? (
          <p className="text-xs text-muted-foreground italic">
            Brak przypisanych TAC-ów.
          </p>
        ) : (
          <ul className="space-y-2">
            {tacs.map((t) => (
              <li
                key={t.id}
                className="flex items-center justify-between bg-card dark:bg-muted border border-border dark:border-border rounded-lg px-3 py-2"
              >
                <div className="flex items-center gap-3">
                  <UserCircle2 className="w-6 h-6 text-purple-500" />
                  <div>
                    <div className="text-sm font-medium flex items-center gap-2">
                      {t.name}
                      {t.is_primary && (
                        <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">
                          <Crown className="w-3 h-3" /> Primary
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {t.email} · {t.role}
                    </div>
                  </div>
                </div>
                {canEdit && (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => togglePrimaryTac.mutate(t.user_id)}
                      className="text-xs px-2 py-1 rounded border border-border dark:border-border hover:bg-muted dark:hover:bg-muted"
                      title={t.is_primary ? "Odznacz primary" : "Ustaw jako primary"}
                    >
                      {t.is_primary ? "Usuń primary" : "Ustaw primary"}
                    </button>
                    <button
                      onClick={() => removeTac.mutate(t.user_id)}
                      className="text-muted-foreground hover:text-destructive"
                      title="Usuń przypisanie"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ── Delivery Leads ───────────────────────────────────────────── */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-foreground dark:text-foreground">
            Delivery Leads
          </h3>
          {canEdit && !addingDl && (
            <button
              onClick={() => setAddingDl(true)}
              className="inline-flex items-center gap-1 text-xs px-3 py-1.5 bg-primary text-white rounded-lg hover:bg-primary/90"
            >
              <Plus className="w-3.5 h-3.5" /> Dodaj DL
            </button>
          )}
        </div>

        {addingDl && canEdit && (
          <div className="bg-muted dark:bg-card/40 rounded-lg p-4 mb-3 space-y-3">
            <label className="block text-xs text-muted-foreground">Użytkownik</label>
            <select
              className="w-full border border-border dark:border-border rounded-lg px-3 py-2 text-sm bg-card dark:bg-muted"
              value={dlUserId}
              onChange={(e) => setDlUserId(e.target.value)}
            >
              <option value="">— wybierz —</option>
              {dlCandidates.map((u) => (
                <option key={u.id} value={u.id}>
                  {userLabel(u)} ({u.role})
                </option>
              ))}
            </select>
            <label className="flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={dlIsHead}
                onChange={(e) => setDlIsHead(e.target.checked)}
              />
              Ustaw jako head (główny DL klienta — auto-assign do nowych projektów)
            </label>
            <div className="flex gap-2">
              <button
                disabled={!dlUserId || addDl.isPending}
                onClick={() =>
                  addDl.mutate({
                    delivery_lead_user_id: Number(dlUserId),
                    client_id: clientId,
                    is_head: dlIsHead,
                  })
                }
                className="text-xs px-3 py-1.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50"
              >
                Dodaj
              </button>
              <button
                onClick={() => {
                  setAddingDl(false);
                  setDlUserId("");
                  setDlIsHead(false);
                }}
                className="text-xs px-3 py-1.5 text-muted-foreground hover:text-foreground"
              >
                Anuluj
              </button>
            </div>
          </div>
        )}

        {dls.length === 0 ? (
          <p className="text-xs text-muted-foreground italic">
            Brak przypisanych Delivery Leadów.
          </p>
        ) : (
          <ul className="space-y-2">
            {dls.map((d) => (
              <li
                key={d.id}
                className="flex items-center justify-between bg-card dark:bg-muted border border-border dark:border-border rounded-lg px-3 py-2"
              >
                <div className="flex items-center gap-3">
                  <UserCircle2 className="w-6 h-6 text-primary" />
                  <div>
                    <div className="text-sm font-medium flex items-center gap-2">
                      {d.name}
                      {d.is_head && (
                        <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700">
                          <Crown className="w-3 h-3" /> Head
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {d.email} · {d.role}
                    </div>
                  </div>
                </div>
                {canEdit && (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => toggleHeadDl.mutate(d.id)}
                      className="text-xs px-2 py-1 rounded border border-border dark:border-border hover:bg-muted dark:hover:bg-muted"
                      title={d.is_head ? "Odznacz head" : "Ustaw jako head"}
                    >
                      {d.is_head ? "Usuń head" : "Ustaw head"}
                    </button>
                    <button
                      onClick={() => removeDl.mutate(d.id)}
                      className="text-muted-foreground hover:text-destructive"
                      title="Usuń przypisanie"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="text-xs text-muted-foreground bg-muted dark:bg-card/40 rounded-lg px-3 py-2">
        <strong>Jak to działa:</strong> przy tworzeniu nowego projektu dla tego
        klienta system automatycznie przypisze <strong>primary TAC</strong> oraz{" "}
        <strong>head Delivery Lead</strong>. Operator może jawnie nadpisać
        wybór — override jest logowany.
      </div>
    </div>
  );
}
