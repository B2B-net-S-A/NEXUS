"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  Loader2,
  MessageSquare,
  Pencil,
  Send,
  Trash2,
  X,
} from "lucide-react";

import {
  teamsChannelsApi,
  type TeamsChannel,
  type TeamsChannelCreateInput,
  type TeamsNotificationType,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import { cn } from "@/lib/utils";

interface NotificationTypeOption {
  value: TeamsNotificationType;
  label: string;
  description: string;
}

const NOTIFICATION_TYPES: NotificationTypeOption[] = [
  {
    value: "candidate_added",
    label: "Nowy kandydat",
    description: "Po dodaniu kandydata do systemu.",
  },
  {
    value: "decision_accepted",
    label: "Weryfikacja zaakceptowana",
    description: "Manager zaakceptował weryfikację kandydata.",
  },
  {
    value: "decision_rejected",
    label: "Weryfikacja odrzucona",
    description: "Manager odrzucił weryfikację kandydata.",
  },
  {
    value: "contract_signed",
    label: "Umowa podpisana",
    description: "Kontrakt aktywowany / draft sfinalizowany.",
  },
];

const EMPTY_FORM: TeamsChannelCreateInput = {
  workspace_label: "",
  team_id: "",
  channel_id: "",
  notification_types: [],
};

function describeTypes(values: TeamsNotificationType[]): string {
  if (values.length === 0) return "Brak typów";
  return values
    .map(
      (v) => NOTIFICATION_TYPES.find((opt) => opt.value === v)?.label ?? v,
    )
    .join(", ");
}

export default function TeamsNotificationsCard() {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [draft, setDraft] = useState<TeamsChannelCreateInput>(EMPTY_FORM);
  const [testingId, setTestingId] = useState<number | null>(null);

  const { data: channels = [], isLoading } = useQuery({
    queryKey: ["teams-channels"],
    queryFn: () => teamsChannelsApi.list(),
    staleTime: 30_000,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["teams-channels"] });

  const createMutation = useMutation({
    mutationFn: (data: TeamsChannelCreateInput) => teamsChannelsApi.create(data),
    onSuccess: () => {
      showSuccess("Kanał Teams został dodany");
      setDraft(EMPTY_FORM);
      invalidate();
    },
    onError: () => showError("Nie udało się dodać kanału Teams"),
  });

  const updateMutation = useMutation({
    mutationFn: ({
      id,
      patch,
    }: {
      id: number;
      patch: Parameters<typeof teamsChannelsApi.update>[1];
    }) => teamsChannelsApi.update(id, patch),
    onSuccess: () => invalidate(),
    onError: () => showError("Nie udało się zaktualizować kanału"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => teamsChannelsApi.delete(id),
    onSuccess: () => {
      showSuccess("Kanał usunięty");
      invalidate();
    },
    onError: () => showError("Nie udało się usunąć kanału"),
  });

  const handleAddType = (value: TeamsNotificationType): void => {
    if (draft.notification_types.includes(value)) {
      setDraft({
        ...draft,
        notification_types: draft.notification_types.filter((t) => t !== value),
      });
      return;
    }
    setDraft({
      ...draft,
      notification_types: [...draft.notification_types, value],
    });
  };

  const handleCreate = (): void => {
    if (
      !draft.workspace_label.trim() ||
      !draft.team_id.trim() ||
      !draft.channel_id.trim()
    ) {
      showError("Wypełnij etykietę, team_id oraz channel_id.");
      return;
    }
    if (draft.notification_types.length === 0) {
      showError("Wybierz co najmniej jeden typ powiadomień.");
      return;
    }
    createMutation.mutate(draft);
  };

  const handleTest = async (channel: TeamsChannel): Promise<void> => {
    setTestingId(channel.id);
    try {
      const result = await teamsChannelsApi.test(channel.id);
      if (result.sent) {
        showSuccess(`Karta testowa wysłana do "${channel.workspace_label}"`);
      } else {
        showError(result.detail || "Test nie powiódł się – sprawdź konfigurację.");
      }
    } catch {
      showError("Test nie powiódł się – sprawdź logi backendu.");
    } finally {
      setTestingId(null);
    }
  };

  return (
    <div className="bg-card dark:bg-muted rounded-2xl border border-border p-6">
      <div className="flex items-start gap-4 mb-6">
        <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center flex-shrink-0">
          <MessageSquare className="w-6 h-6 text-primary" />
        </div>
        <div className="flex-1">
          <h3 className="text-base font-bold text-foreground">
            Powiadomienia Microsoft Teams
          </h3>
          <p className="text-sm text-muted-foreground mt-0.5">
            Karty Adaptive Cards na wybrane kanały Teams po kluczowych zdarzeniach
            ATS (nowy kandydat, decyzja, podpisana umowa).
          </p>
        </div>
      </div>

      <div className="rounded-lg border border-border bg-background/40 p-4 text-sm text-muted-foreground mb-5">
        Wymaga zgody admina dla{" "}
        <code className="px-1 py-0.5 rounded bg-muted text-foreground">
          ChannelMessage.Send
        </code>{" "}
        (Application permission) w Azure AD oraz ustawienia{" "}
        <code className="px-1 py-0.5 rounded bg-muted text-foreground">
          TEAMS_NOTIFICATIONS_ENABLED=true
        </code>{" "}
        w Coolify env vault. Team ID i Channel ID skopiujesz w Teams:
        kliknij &quot;...&quot; przy nazwie kanału → &quot;Get link to
        channel&quot; → URL zawiera oba ID.
      </div>

      <h4 className="text-sm font-medium text-foreground mb-3">
        Skonfigurowane kanały
      </h4>
      {isLoading ? (
        <div className="py-6 text-center text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin inline mr-2" />
          Ładowanie...
        </div>
      ) : channels.length === 0 ? (
        <div className="py-6 text-center text-sm text-muted-foreground rounded-lg border border-dashed border-border">
          Brak skonfigurowanych kanałów. Dodaj pierwszy poniżej.
        </div>
      ) : (
        <ul className="space-y-2 mb-6">
          {channels.map((channel) => (
            <ChannelRow
              key={channel.id}
              channel={channel}
              busy={
                testingId === channel.id ||
                updateMutation.isPending ||
                deleteMutation.isPending
              }
              onToggle={(enabled) =>
                updateMutation.mutate({ id: channel.id, patch: { enabled } })
              }
              onTypesChange={(types) =>
                updateMutation.mutate({
                  id: channel.id,
                  patch: { notification_types: types },
                })
              }
              onTest={() => handleTest(channel)}
              onDelete={() => deleteMutation.mutate(channel.id)}
            />
          ))}
        </ul>
      )}

      <div className="rounded-xl border border-border bg-background/40 p-4 space-y-3">
        <h4 className="text-sm font-semibold text-foreground">Dodaj nowy kanał</h4>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <input
            type="text"
            placeholder="Etykieta (np. ATS Deals)"
            value={draft.workspace_label}
            onChange={(e) =>
              setDraft({ ...draft, workspace_label: e.target.value })
            }
            className="rounded-md border border-border bg-background px-3 py-2 text-sm"
          />
          <input
            type="text"
            placeholder="Team ID"
            value={draft.team_id}
            onChange={(e) => setDraft({ ...draft, team_id: e.target.value })}
            className="rounded-md border border-border bg-background px-3 py-2 text-sm font-mono"
          />
          <input
            type="text"
            placeholder="Channel ID"
            value={draft.channel_id}
            onChange={(e) =>
              setDraft({ ...draft, channel_id: e.target.value })
            }
            className="rounded-md border border-border bg-background px-3 py-2 text-sm font-mono"
          />
        </div>

        <div>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
            Typy powiadomień
          </p>
          <div className="flex flex-wrap gap-2">
            {NOTIFICATION_TYPES.map((opt) => {
              const active = draft.notification_types.includes(opt.value);
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => handleAddType(opt.value)}
                  title={opt.description}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs transition-colors",
                    active
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-background text-muted-foreground hover:border-primary hover:text-foreground",
                  )}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>
        </div>

        <button
          type="button"
          onClick={handleCreate}
          disabled={createMutation.isPending}
          className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {createMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <CheckCircle2 className="h-4 w-4" />
          )}
          Dodaj kanał
        </button>
      </div>
    </div>
  );
}

interface ChannelRowProps {
  channel: TeamsChannel;
  busy: boolean;
  onToggle: (enabled: boolean) => void;
  onTypesChange: (types: TeamsNotificationType[]) => void;
  onTest: () => void;
  onDelete: () => void;
}

function ChannelRow({
  channel,
  busy,
  onToggle,
  onTypesChange,
  onTest,
  onDelete,
}: ChannelRowProps) {
  const [editing, setEditing] = useState(false);
  const [localTypes, setLocalTypes] = useState<TeamsNotificationType[]>(
    channel.notification_types,
  );

  const handleSave = (): void => {
    onTypesChange(localTypes);
    setEditing(false);
  };

  return (
    <li className="rounded-lg border border-border bg-background/40 px-4 py-3 text-sm">
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-foreground">
              {channel.workspace_label}
            </span>
            <span
              className={cn(
                "text-xs px-2 py-0.5 rounded-full font-medium",
                channel.enabled
                  ? "bg-green-100 text-green-700"
                  : "bg-muted text-muted-foreground",
              )}
            >
              {channel.enabled ? "Aktywny" : "Wyłączony"}
            </span>
          </div>
          <p className="text-xs text-muted-foreground mt-1 font-mono break-all">
            team={channel.team_id} · channel={channel.channel_id}
          </p>
          {editing ? (
            <div className="mt-2 flex flex-wrap gap-2">
              {NOTIFICATION_TYPES.map((opt) => {
                const active = localTypes.includes(opt.value);
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() =>
                      setLocalTypes(
                        active
                          ? localTypes.filter((t) => t !== opt.value)
                          : [...localTypes, opt.value],
                      )
                    }
                    className={cn(
                      "rounded-full border px-2.5 py-0.5 text-xs",
                      active
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border bg-background text-muted-foreground",
                    )}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground mt-1">
              {describeTypes(channel.notification_types)}
            </p>
          )}
        </div>

        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            type="button"
            onClick={() => onToggle(!channel.enabled)}
            disabled={busy}
            title={channel.enabled ? "Wyłącz" : "Włącz"}
            className={cn(
              "relative inline-flex h-5 w-9 cursor-pointer rounded-full transition-colors disabled:opacity-50",
              channel.enabled ? "bg-primary" : "bg-muted",
            )}
          >
            <span
              className={cn(
                "pointer-events-none inline-block h-4 w-4 transform rounded-full bg-card shadow ring-0 transition-transform mt-0.5",
                channel.enabled ? "translate-x-4" : "translate-x-0.5",
              )}
            />
          </button>
          {editing ? (
            <>
              <button
                type="button"
                onClick={handleSave}
                disabled={busy}
                title="Zapisz"
                className="p-1.5 text-primary hover:bg-muted rounded disabled:opacity-50"
              >
                <CheckCircle2 className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={() => {
                  setLocalTypes(channel.notification_types);
                  setEditing(false);
                }}
                className="p-1.5 text-muted-foreground hover:bg-muted rounded"
                title="Anuluj"
              >
                <X className="h-4 w-4" />
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={() => setEditing(true)}
                disabled={busy}
                title="Edytuj typy"
                className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted rounded disabled:opacity-50"
              >
                <Pencil className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={onTest}
                disabled={busy}
                title="Wyślij testową kartę"
                className="p-1.5 text-muted-foreground hover:text-primary hover:bg-muted rounded disabled:opacity-50"
              >
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </button>
              <button
                type="button"
                onClick={() => {
                  if (
                    confirm(
                      `Usunąć kanał "${channel.workspace_label}"? Tej akcji nie można cofnąć.`,
                    )
                  ) {
                    onDelete();
                  }
                }}
                disabled={busy}
                title="Usuń"
                className="p-1.5 text-muted-foreground hover:text-destructive hover:bg-muted rounded disabled:opacity-50"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </>
          )}
        </div>
      </div>
      {!channel.enabled && (
        <div className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <AlertCircle className="h-3 w-3" />
          Kanał wyłączony – nie otrzyma powiadomień.
        </div>
      )}
    </li>
  );
}
