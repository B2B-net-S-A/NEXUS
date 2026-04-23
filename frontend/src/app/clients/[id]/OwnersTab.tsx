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
      toast.show({ kind: "success", message: "TAC dodany" });
      setAddingTac(false);
      setTacUserId("");
      setTacIsPrimary(false);
      invalidate();
    },
    onError: (e: any) =>
      toast.show({
        kind: "error",
        message: e?.response?.data?.detail || "Błąd dodawania TAC",
      }),
  });

  const removeTac = useMutation({
    mutationFn: (userId: number) =>
      api.delete(`/api/clients/${clientId}/tacs/${userId}`),
    onSuccess: () => {
      toast.show({ kind: "success", message: "TAC usunięty" });
      invalidate();
    },
  });

  const togglePrimaryTac = useMutation({
    mutationFn: (userId: number) =>
      api.put(`/api/clients/${clientId}/tacs/${userId}/toggle-primary`),
    onSuccess: () => {
      toast.show({ kind: "success", message: "Primary TAC zmieniony" });
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
      toast.show({ kind: "success", message: "Delivery Lead dodany" });
      setAddingDl(false);
      setDlUserId("");
      setDlIsHead(false);
      invalidate();
    },
    onError: (e: any) =>
      toast.show({
        kind: "error",
        message: e?.response?.data?.detail || "Błąd dodawania DL",
      }),
  });

  const removeDl = useMutation({
    mutationFn: (assignmentId: number) =>
      api.delete(`/api/team-structure/dl-clients/${assignmentId}`),
    onSuccess: () => {
      toast.show({ kind: "success", message: "DL usunięty" });
      invalidate();
    },
  });

  const toggleHeadDl = useMutation({
    mutationFn: (assignmentId: number) =>
      api.put(`/api/team-structure/dl-clients/${assignmentId}/toggle-head`),
    onSuccess: () => {
      toast.show({ kind: "success", message: "Head DL zmieniony" });
      invalidate();
    },
  });

  if (isLoading) {
    return (
      <div className="p-6 text-gray-400 text-sm">Ładowanie opiekunów…</div>
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
        <div className="text-xs text-gray-500 bg-gray-50 dark:bg-gray-900/40 rounded-lg px-3 py-2">
          Widok tylko do odczytu. Edycja opiekunów klienta wymaga roli
          <strong> admin</strong> lub <strong>head_of_recruitment</strong>.
        </div>
      )}

      {/* ── TAC ──────────────────────────────────────────────────────── */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
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
          <div className="bg-gray-50 dark:bg-gray-900/40 rounded-lg p-4 mb-3 space-y-3">
            <label className="block text-xs text-gray-600">Użytkownik</label>
            <select
              className="w-full border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-800"
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
                className="text-xs px-3 py-1.5 text-gray-600 hover:text-gray-900"
              >
                Anuluj
              </button>
            </div>
          </div>
        )}

        {tacs.length === 0 ? (
          <p className="text-xs text-gray-400 italic">
            Brak przypisanych TAC-ów.
          </p>
        ) : (
          <ul className="space-y-2">
            {tacs.map((t) => (
              <li
                key={t.id}
                className="flex items-center justify-between bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2"
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
                    <div className="text-xs text-gray-500">
                      {t.email} · {t.role}
                    </div>
                  </div>
                </div>
                {canEdit && (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => togglePrimaryTac.mutate(t.user_id)}
                      className="text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700"
                      title={t.is_primary ? "Odznacz primary" : "Ustaw jako primary"}
                    >
                      {t.is_primary ? "Usuń primary" : "Ustaw primary"}
                    </button>
                    <button
                      onClick={() => removeTac.mutate(t.user_id)}
                      className="text-gray-400 hover:text-red-600"
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
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            Delivery Leads
          </h3>
          {canEdit && !addingDl && (
            <button
              onClick={() => setAddingDl(true)}
              className="inline-flex items-center gap-1 text-xs px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              <Plus className="w-3.5 h-3.5" /> Dodaj DL
            </button>
          )}
        </div>

        {addingDl && canEdit && (
          <div className="bg-gray-50 dark:bg-gray-900/40 rounded-lg p-4 mb-3 space-y-3">
            <label className="block text-xs text-gray-600">Użytkownik</label>
            <select
              className="w-full border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-800"
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
                className="text-xs px-3 py-1.5 text-gray-600 hover:text-gray-900"
              >
                Anuluj
              </button>
            </div>
          </div>
        )}

        {dls.length === 0 ? (
          <p className="text-xs text-gray-400 italic">
            Brak przypisanych Delivery Leadów.
          </p>
        ) : (
          <ul className="space-y-2">
            {dls.map((d) => (
              <li
                key={d.id}
                className="flex items-center justify-between bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2"
              >
                <div className="flex items-center gap-3">
                  <UserCircle2 className="w-6 h-6 text-blue-500" />
                  <div>
                    <div className="text-sm font-medium flex items-center gap-2">
                      {d.name}
                      {d.is_head && (
                        <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700">
                          <Crown className="w-3 h-3" /> Head
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-gray-500">
                      {d.email} · {d.role}
                    </div>
                  </div>
                </div>
                {canEdit && (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => toggleHeadDl.mutate(d.id)}
                      className="text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700"
                      title={d.is_head ? "Odznacz head" : "Ustaw jako head"}
                    >
                      {d.is_head ? "Usuń head" : "Ustaw head"}
                    </button>
                    <button
                      onClick={() => removeDl.mutate(d.id)}
                      className="text-gray-400 hover:text-red-600"
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

      <div className="text-xs text-gray-400 bg-gray-50 dark:bg-gray-900/40 rounded-lg px-3 py-2">
        <strong>Jak to działa:</strong> przy tworzeniu nowego projektu dla tego
        klienta system automatycznie przypisze <strong>primary TAC</strong> oraz{" "}
        <strong>head Delivery Lead</strong>. Operator może jawnie nadpisać
        wybór — override jest logowany.
      </div>
    </div>
  );
}
