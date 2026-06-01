"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Phone,
  RefreshCw,
} from "lucide-react";

import api, { cloudtalkApi, type CloudTalkAgent } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { cn } from "@/lib/utils";

interface HealthChecks {
  cloudtalk?: "healthy" | "degraded" | "unconfigured" | "unhealthy";
}

interface UserOption {
  id: number;
  email: string;
  name: string;
}

function statusBadgeClass(s?: string): string {
  switch (s) {
    case "healthy":
      return "bg-green-100 text-green-700";
    case "degraded":
      return "bg-amber-100 text-amber-700";
    case "unhealthy":
      return "bg-destructive/15 text-destructive";
    default:
      return "bg-muted text-muted-foreground";
  }
}

function statusLabel(s?: string): string {
  switch (s) {
    case "healthy":
      return "Połączony";
    case "degraded":
      return "Wolne / timeout";
    case "unhealthy":
      return "Błąd autoryzacji";
    case "unconfigured":
      return "Wyłączony";
    default:
      return "Sprawdzanie...";
  }
}

/**
 * Settings card for CloudTalk: health status, agent ↔ user mapping table,
 * sync button. Hides itself entirely when `/api/health.checks.cloudtalk`
 * reports `unconfigured` for the very first time (until the admin flips
 * `CLOUDTALK_ENABLED=true` in Coolify), so the page stays clean.
 */
export default function CloudTalkSettingsCard() {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [busyAgent, setBusyAgent] = useState<number | null>(null);

  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ["cloudtalk-health"],
    queryFn: async () =>
      api.get<{ checks?: HealthChecks }>("/api/health").then((r) => r.data),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
  const status = health?.checks?.cloudtalk;
  const isEnabled = status && status !== "unconfigured";

  const { data: agents = [], isFetching: agentsLoading } = useQuery({
    queryKey: ["cloudtalk-agents"],
    queryFn: () => cloudtalkApi.listAgents(),
    enabled: !!isEnabled,
    staleTime: 60_000,
  });

  const { data: users = [] } = useQuery({
    queryKey: ["cloudtalk-users-for-mapping"],
    queryFn: () =>
      api.get<UserOption[]>("/api/users").then((r) => r.data),
    enabled: !!isEnabled,
    staleTime: 5 * 60_000,
  });

  const syncMutation = useMutation({
    mutationFn: () => cloudtalkApi.syncAgents(),
    onSuccess: (data) => {
      showSuccess(
        `Zsynchronizowano: ${data.linked} nowo zmapowanych, ${data.already_linked} już zmapowanych, ${data.unmatched.length} bez dopasowania`,
      );
      queryClient.invalidateQueries({ queryKey: ["cloudtalk-agents"] });
    },
    onError: () => showError("Synchronizacja agentów nie powiodła się"),
  });

  const handleAssign = async (agent: CloudTalkAgent, userId: number) => {
    setBusyAgent(agent.id);
    try {
      if (userId === 0) {
        await cloudtalkApi.unassignAgent(agent.id);
      } else {
        await cloudtalkApi.assignAgent(agent.id, userId);
      }
      queryClient.invalidateQueries({ queryKey: ["cloudtalk-agents"] });
    } catch {
      showError("Nie udało się zapisać mapowania");
    } finally {
      setBusyAgent(null);
    }
  };

  return (
    <div className="bg-card dark:bg-muted rounded-2xl border border-border p-6">
      <div className="flex items-start gap-4 mb-6">
        <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center flex-shrink-0">
          <Phone className="w-6 h-6 text-primary" />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-bold text-foreground">CloudTalk</h3>
            <span
              className={cn(
                "text-xs px-2 py-0.5 rounded-full font-medium",
                statusBadgeClass(status),
              )}
            >
              {healthLoading ? "Sprawdzanie..." : statusLabel(status)}
            </span>
          </div>
          <p className="text-sm text-muted-foreground mt-0.5">
            Telefonia: rejestrowanie rozmów, transkrypty, click-to-call z profili
            kandydatów.
          </p>
        </div>
        <a
          href="https://my.cloudtalk.io"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-primary"
        >
          Panel <ExternalLink className="h-3.5 w-3.5" />
        </a>
      </div>

      {!isEnabled && (
        <div className="rounded-lg border border-border bg-background/40 p-4 text-sm text-muted-foreground">
          Integracja CloudTalk jest wyłączona. Aby aktywować, ustaw{" "}
          <code className="px-1 py-0.5 rounded bg-muted text-foreground">
            CLOUDTALK_ENABLED=true
          </code>{" "}
          oraz API key i webhook secret w Coolify env vault.
        </div>
      )}

      {isEnabled && status === "unhealthy" && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive flex items-start gap-2 mb-4">
          <AlertCircle className="h-4 w-4 mt-0.5" />
          <div>
            CloudTalk zwraca 401/403 – zweryfikuj{" "}
            <code className="font-mono text-xs">CLOUDTALK_API_KEY_SECRET</code>{" "}
            w Coolify.
          </div>
        </div>
      )}

      {isEnabled && (
        <>
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-sm font-medium text-foreground">
              Mapowanie agentów
            </h4>
            <button
              type="button"
              onClick={() => syncMutation.mutate()}
              disabled={syncMutation.isPending}
              className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline disabled:opacity-50"
            >
              {syncMutation.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              Synchronizuj
            </button>
          </div>

          {agentsLoading && agents.length === 0 ? (
            <div className="py-6 text-center text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin inline mr-2" />
              Pobieranie agentów...
            </div>
          ) : agents.length === 0 ? (
            <div className="py-6 text-center text-sm text-muted-foreground">
              Brak agentów w CloudTalk.
            </div>
          ) : (
            <div className="rounded-lg border border-border overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-background/40">
                  <tr className="text-left">
                    <th className="px-3 py-2 font-medium text-muted-foreground">
                      Agent
                    </th>
                    <th className="px-3 py-2 font-medium text-muted-foreground">
                      Email
                    </th>
                    <th className="px-3 py-2 font-medium text-muted-foreground">
                      Powiązany user
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {agents.map((agent) => (
                    <tr key={agent.id} className="border-t border-border">
                      <td className="px-3 py-2">
                        {[agent.firstname, agent.lastname]
                          .filter(Boolean)
                          .join(" ") || `Agent #${agent.id}`}
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {agent.email || "–"}
                      </td>
                      <td className="px-3 py-2">
                        <select
                          className="w-full rounded-md border border-border bg-background px-2 py-1 text-sm"
                          value={agent.linked_user_id || 0}
                          disabled={busyAgent === agent.id}
                          onChange={(e) =>
                            handleAssign(agent, Number(e.target.value))
                          }
                        >
                          <option value={0}>– Brak –</option>
                          {users.map((u) => (
                            <option key={u.id} value={u.id}>
                              {u.email}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="mt-3 text-xs text-muted-foreground flex items-center gap-1">
            <CheckCircle2 className="h-3 w-3" />
            Webhooki przychodzące:{" "}
            <code className="font-mono text-xs">/api/calls/webhook</code> –
            CloudTalk panel → Integrations → Webhooks
          </div>
        </>
      )}
    </div>
  );
}
