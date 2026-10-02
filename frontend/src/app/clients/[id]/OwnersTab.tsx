"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Crown, Plus, Target, Trash2, UserCircle2 } from "lucide-react";
import api, { clientTeamApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import type { ClientTeamResponse, ClientTeamTacAssignment } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
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
import { formatIsoDatePl } from "@/lib/date-pl";
import { TAC_UI_ENABLED } from "@/lib/tac-ui";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { hasRole, useAuthStore } from "@/store/auth";

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

function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase();
}

export function OwnersTab({ clientId }: { clientId: number }) {
  const qc = useQueryClient();
  const toast = useToast();
  const me = useAuthStore((s) => s.user);
  // Multi-role aware (`hasRole`): sama rola główna chowała edycję przed
  // hybrydą z dodatkową rolą admin/HoR (audyt N6).
  const canEdit = hasRole(me, "admin", "head_of_recruitment");
  // Funkcji TAC nie używamy (decyzja 22.09.2026, `lib/tac-ui.ts`) — sekcja TAC
  // i opis pierwszego priorytetu znikają razem z resztą UI TAC-a.
  const showTac = TAC_UI_ENABLED;

  const teamQuery = useQuery<ClientTeamResponse>({
    queryKey: ["client-team", clientId],
    queryFn: () => clientTeamApi.get(clientId).then((r) => r.data),
  });
  const team = teamQuery.data;
  // Awaria ≠ „Brak przypisanych Delivery Leadów” (audyt S10).
  const teamState = resolveViewState({
    isLoading: teamQuery.isPending,
    isError: teamQuery.isError,
    error: teamQuery.error,
    isSuccess: teamQuery.isSuccess,
  });

  const { data: allUsers } = useQuery<AppUser[]>({
    queryKey: ["users-list-owners"],
    queryFn: () => api.get<AppUser[]>("/api/users").then((r) => r.data),
    enabled: canEdit,
  });

  const [addingTac, setAddingTac] = useState(false);
  const [addingDl, setAddingDl] = useState(false);
  const [tacUserId, setTacUserId] = useState("");
  const [tacIsFirstPriority, setTacIsFirstPriority] = useState(false);
  const [dlUserId, setDlUserId] = useState("");
  const [dlIsHead, setDlIsHead] = useState(false);

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["client-team", clientId] });

  const addTac = useMutation({
    mutationFn: (body: {
      user_id: number;
      is_first_priority_for_tac?: true;
    }) => clientTeamApi.addTac(clientId, body),
    onSuccess: () => {
      toast.showSuccess("TAC dodany");
      setAddingTac(false);
      setTacUserId("");
      setTacIsFirstPriority(false);
      invalidate();
    },
    onError: (e: any) =>
      toast.showError(apiErrorMessage(e, "Błąd dodawania TAC")),
  });

  const removeTac = useMutation({
    mutationFn: (userId: number) =>
      clientTeamApi.removeTac(clientId, userId),
    retry: false,
    onSuccess: () => {
      toast.showSuccess("TAC usunięty");
      invalidate();
    },
    onError: (e: any) =>
      toast.showError(
        apiErrorMessage(
          e,
          "Nie można usunąć TAC-a z jego klienta priorytetowego. Najpierw ustaw innego klienta jako priorytet #1 z jego karty.",
        ),
      ),
  });

  const setFirstPriorityTac = useMutation({
    mutationFn: (tac: ClientTeamTacAssignment) =>
      clientTeamApi.setTacFirstPriority(clientId, tac.user_id, {
        enabled: true,
      }),
    onSuccess: () => {
      toast.showSuccess("Pierwszy priorytet TAC-a zmieniony");
      invalidate();
    },
    onError: (e: any) =>
      toast.showError(
        apiErrorMessage(e, "Błąd zmiany pierwszego priorytetu TAC-a"),
      ),
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
      toast.showError(apiErrorMessage(e, "Błąd dodawania DL")),
  });

  const removeDl = useMutation({
    mutationFn: (assignmentId: number) =>
      api.delete(`/api/team-structure/dl-clients/${assignmentId}`),
    onSuccess: () => {
      toast.showSuccess("DL usunięty");
      invalidate();
    },
    // Bez `onError` nieudane usunięcie nie mówiło nic (audyt N6).
    onError: (e: unknown) =>
      toast.showError(apiErrorMessage(e, "Nie udało się usunąć Delivery Leada")),
  });

  const toggleHeadDl = useMutation({
    mutationFn: (assignmentId: number) =>
      api.put(`/api/team-structure/dl-clients/${assignmentId}/toggle-head`),
    onSuccess: () => {
      toast.showSuccess("Head DL zmieniony");
      invalidate();
    },
    onError: (e: unknown) =>
      toast.showError(apiErrorMessage(e, "Nie udało się zmienić head DL")),
  });

  if (teamState === "loading") {
    return (
      <div className="p-6 text-muted-foreground text-sm">Ładowanie opiekunów…</div>
    );
  }
  if (isBlockingViewState(teamState)) {
    return (
      <QueryStateNotice
        state={teamState as "forbidden" | "not_found" | "error"}
        description={
          teamState === "error" ? "Nie udało się wczytać opiekunów klienta." : undefined
        }
        onRetry={() => void teamQuery.refetch()}
      />
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
    <div className="space-y-4">
      {!canEdit && (
        <div className="text-xs text-muted-foreground bg-muted rounded-lg px-3 py-2">
          Widok tylko do odczytu. Edycja opiekunów klienta wymaga roli
          <strong> admin</strong> lub <strong>head_of_recruitment</strong>.
        </div>
      )}

      {/* ── TAC ──────────────────────────────────────────────────────── */}
      {showTac ? (
        <section>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-foreground">
              TAC (Talent Acquisition Consultants)
            </h3>
            {canEdit && !addingTac && (
              <button
                onClick={() => setAddingTac(true)}
                className="inline-flex items-center gap-1 text-xs px-3 py-1.5 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90"
              >
                <Plus className="w-3.5 h-3.5" /> Dodaj TAC
              </button>
            )}
          </div>

          {addingTac && canEdit && (
            <div className="bg-muted rounded-lg p-4 mb-3 space-y-3">
              <label className="block text-xs text-muted-foreground">Użytkownik</label>
              <select
                className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-card dark:bg-muted"
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
                  checked={tacIsFirstPriority}
                  onChange={(e) => setTacIsFirstPriority(e.target.checked)}
                />
                Ustaw tego klienta jako pierwszy priorytet tego TAC-a
              </label>
              <div className="flex gap-2">
                <button
                  disabled={!tacUserId || addTac.isPending}
                  onClick={() =>
                    addTac.mutate(
                      tacIsFirstPriority
                        ? {
                            user_id: Number(tacUserId),
                            is_first_priority_for_tac: true,
                          }
                        : { user_id: Number(tacUserId) },
                    )
                  }
                  className="text-xs px-3 py-1.5 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50"
                >
                  Dodaj
                </button>
                <button
                  onClick={() => {
                    setAddingTac(false);
                    setTacUserId("");
                    setTacIsFirstPriority(false);
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
                  className="flex flex-wrap items-center justify-between gap-2 bg-card dark:bg-muted border border-border rounded-lg px-3 py-2"
                >
                  <div className="flex min-w-0 flex-1 items-center gap-3">
                    <UserCircle2 className="w-6 h-6 shrink-0 text-muted-foreground" />
                    <div className="min-w-0">
                      <div className="text-sm font-medium flex flex-wrap items-center gap-2">
                        {t.name}
                        {t.is_first_priority_for_tac && (
                          <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                            <Target className="w-3 h-3" /> 1. priorytet tego TAC-a
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-muted-foreground break-all">
                        {t.email} · {t.role}
                      </div>
                    </div>
                  </div>
                  {canEdit && (
                    <div className="ml-auto flex items-center gap-2 pointer-coarse:gap-4">
                      {t.is_first_priority_for_tac ? (
                        <span
                          className="text-[11px] text-muted-foreground max-w-48 text-right"
                          title="Pierwszy priorytet musi mieć następcę"
                        >
                          Ustaw innego klienta jako priorytet #1 z jego karty
                        </span>
                      ) : (
                        <button
                          onClick={() => setFirstPriorityTac.mutate(t)}
                          disabled={setFirstPriorityTac.isPending}
                          className="text-xs px-2 py-1 rounded border border-border hover:bg-muted pointer-coarse:min-h-10"
                          title="Ustaw klienta jako pierwszy priorytet tego TAC-a"
                        >
                          Ustaw 1. priorytet
                        </button>
                      )}
                      <button
                        onClick={() => removeTac.mutate(t.user_id)}
                        className="hit-area text-muted-foreground hover:text-destructive"
                        title="Usuń przypisanie"
                        aria-label="Usuń przypisanie"
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
      ) : null}

      {/* ── Delivery Leads ───────────────────────────────────────────── */}
      <section>
        <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
          <h3 className="flex items-center gap-2 text-[13px] font-semibold text-foreground">
            Delivery Leads
            <span className="rounded-full bg-muted px-1.5 text-[11px] font-semibold leading-[18px] text-muted-foreground tabular-nums">
              {dls.length}
            </span>
          </h3>
          <span className="text-xs text-muted-foreground">
            Główny DL (head) jest wpisywany do nowych projektów klienta.
          </span>
          {canEdit && !addingDl && (
            <Button
              size="sm"
              variant="primary"
              className="ml-auto"
              onClick={() => setAddingDl(true)}
            >
              <Plus className="w-3.5 h-3.5" aria-hidden="true" /> Dodaj DL
            </Button>
          )}
        </div>

        {addingDl && canEdit && (
          <div className="bg-muted rounded-lg p-4 mb-3 space-y-3">
            <label className="block text-xs text-muted-foreground">Użytkownik</label>
            <select
              className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-card"
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
              <Button
                size="sm"
                variant="primary"
                disabled={!dlUserId || addDl.isPending}
                onClick={() =>
                  addDl.mutate({
                    delivery_lead_user_id: Number(dlUserId),
                    client_id: clientId,
                    is_head: dlIsHead,
                  })
                }
              >
                Dodaj
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setAddingDl(false);
                  setDlUserId("");
                  setDlIsHead(false);
                }}
              >
                Anuluj
              </Button>
            </div>
          </div>
        )}

        {dls.length === 0 ? (
          <p className="text-xs text-muted-foreground italic">
            Brak przypisanych Delivery Leadów.
          </p>
        ) : (
          <Table density="compact" className="min-w-[560px]">
            <TableHeader>
              <TableRow>
                <TableHead className={CALM_HEAD}>Osoba</TableHead>
                <TableHead className={CALM_HEAD}>Rola u klienta</TableHead>
                <TableHead className={CALM_HEAD}>Przypisano</TableHead>
                {canEdit ? (
                  <TableHead className={`${CALM_HEAD} text-right`}>Akcje</TableHead>
                ) : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {dls.map((d) => (
                <TableRow key={d.id} className="h-[54px]">
                  <TableCell>
                    <div className="flex items-center gap-2.5">
                      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-muted">
                        <span className="text-[10.5px] font-semibold text-muted-foreground">
                          {initialsOf(d.name)}
                        </span>
                      </div>
                      <div className="min-w-0">
                        <span className="font-semibold text-foreground">{d.name}</span>
                        <span className={`${CALM_SUBLINE} break-all`}>
                          {d.email} · {d.role}
                        </span>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    {d.is_head ? (
                      <Badge size="sm" variant="success" title="Główny Delivery Lead klienta">
                        <Crown className="h-2.5 w-2.5" aria-hidden="true" /> Head
                      </Badge>
                    ) : (
                      <span className="text-xs text-muted-foreground">Delivery Lead</span>
                    )}
                  </TableCell>
                  <TableCell className="whitespace-nowrap tabular-nums">
                    {d.created_at ? (
                      formatIsoDatePl(d.created_at)
                    ) : (
                      <span className={CALM_EMPTY}>—</span>
                    )}
                  </TableCell>
                  {canEdit ? (
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => toggleHeadDl.mutate(d.id)}
                          title={d.is_head ? "Odznacz head" : "Ustaw jako head"}
                        >
                          {d.is_head ? "Usuń head" : "Ustaw head"}
                        </Button>
                        <Button
                          size="sm"
                          variant="quiet"
                          onClick={() => removeDl.mutate(d.id)}
                          title="Usuń przypisanie"
                          aria-label="Usuń przypisanie"
                        >
                          <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                          Usuń
                        </Button>
                      </div>
                    </TableCell>
                  ) : null}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>

      {showTac ? (
        <div className="text-xs text-muted-foreground bg-muted rounded-lg px-3 py-2">
          <strong>Jak to działa:</strong> wszyscy przypisani TAC-owie są
          równorzędni. „1. priorytet” opisuje osobistą kolejność pracy konkretnego
          TAC-a — nie robi z niego głównego opiekuna klienta. Przy jednym TAC-u
          nowy request może dostać go jako prefill; przy kilku trzeba jawnie
          wybrać ownera requestu. <strong>Head Delivery Lead</strong> nadal może
          zostać uzupełniony automatycznie.
        </div>
      ) : null}
    </div>
  );
}
