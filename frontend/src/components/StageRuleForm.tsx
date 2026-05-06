"use client";

import { useEffect, useState } from "react";
import { Loader2, Save, X } from "lucide-react";
import { api, type RecipientType, type StageNotificationRuleInput } from "@/lib/api";

const RECIPIENT_LABELS: Record<RecipientType, string> = {
  job_delivery_lead: "Delivery Lead projektu",
  job_recruiter: "Rekruter projektu",
  client_head_dl: "Head DL klienta",
  client_primary_tac: "Primary TAC klienta",
  specific_user: "Konkretny użytkownik",
  role: "Rola (wszyscy aktywni)",
  candidate_creator: "Twórca kandydata",
};

const RECIPIENT_ORDER: RecipientType[] = [
  "job_delivery_lead",
  "job_recruiter",
  "client_head_dl",
  "client_primary_tac",
  "candidate_creator",
  "specific_user",
  "role",
];

const ROLE_OPTIONS: { value: string; label: string }[] = [
  { value: "admin", label: "Admin" },
  { value: "head_of_recruitment", label: "Head of Recruitment" },
  { value: "delivery_lead", label: "Delivery Lead" },
  { value: "tac", label: "TAC" },
  { value: "recruiter", label: "Rekruter" },
  { value: "sourcer", label: "Sourcer" },
];

interface UserOption {
  id: number;
  name: string;
  email: string;
}

interface StageRuleFormProps {
  initial?: Partial<StageNotificationRuleInput>;
  onCancel: () => void;
  onSave: (data: StageNotificationRuleInput) => Promise<void>;
  saveLabel?: string;
}

export function StageRuleForm({
  initial,
  onCancel,
  onSave,
  saveLabel = "Zapisz",
}: StageRuleFormProps) {
  const [recipientType, setRecipientType] = useState<RecipientType>(
    initial?.recipient_type ?? "job_recruiter",
  );
  const [specificUserId, setSpecificUserId] = useState<number | null>(
    initial?.specific_user_id ?? null,
  );
  const [role, setRole] = useState<string>(initial?.role ?? "");
  const [notifyInapp, setNotifyInapp] = useState<boolean>(
    initial?.notify_inapp ?? true,
  );
  const [notifyEmail, setNotifyEmail] = useState<boolean>(
    initial?.notify_email ?? false,
  );
  const [isActive, setIsActive] = useState<boolean>(initial?.is_active ?? true);
  const [users, setUsers] = useState<UserOption[]>([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Lazy-load user list when needed.
  useEffect(() => {
    if (recipientType !== "specific_user" || users.length > 0) return;
    let cancel = false;
    (async () => {
      setUsersLoading(true);
      try {
        const res = await api.get<UserOption[]>("/api/users");
        if (!cancel) setUsers(res.data);
      } catch (err: unknown) {
        if (!cancel) {
          console.error("Failed to load users", err);
        }
      } finally {
        if (!cancel) setUsersLoading(false);
      }
    })();
    return () => {
      cancel = true;
    };
  }, [recipientType, users.length]);

  const validate = (): string | null => {
    if (!notifyInapp && !notifyEmail) {
      return "Wybierz przynajmniej jeden kanał (in-app albo email).";
    }
    if (recipientType === "specific_user" && !specificUserId) {
      return "Wybierz konkretnego użytkownika.";
    }
    if (recipientType === "role" && !role) {
      return "Wybierz rolę.";
    }
    return null;
  };

  const handleSave = async () => {
    setError(null);
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    setSaving(true);
    try {
      await onSave({
        recipient_type: recipientType,
        specific_user_id:
          recipientType === "specific_user" ? specificUserId : null,
        role: recipientType === "role" ? role : null,
        notify_inapp: notifyInapp,
        notify_email: notifyEmail,
        is_active: isActive,
      });
    } catch (err: unknown) {
      const detail =
        err && typeof err === "object" && "response" in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data
              ?.detail
          : null;
      setError(detail ?? "Nie udało się zapisać reguły.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3 rounded-md border border-border dark:border-border bg-muted dark:bg-card/40 p-3">
      <div className="space-y-2">
        <label className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground">
          Adresat
        </label>
        <select
          value={recipientType}
          onChange={(e) => setRecipientType(e.target.value as RecipientType)}
          className="w-full rounded-md border border-border dark:border-border bg-card dark:bg-muted px-2 py-1.5 text-sm"
        >
          {RECIPIENT_ORDER.map((rt) => (
            <option key={rt} value={rt}>
              {RECIPIENT_LABELS[rt]}
            </option>
          ))}
        </select>
      </div>

      {recipientType === "specific_user" && (
        <div className="space-y-1">
          <label className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground">
            Użytkownik
          </label>
          <select
            value={specificUserId ?? ""}
            onChange={(e) =>
              setSpecificUserId(e.target.value ? Number(e.target.value) : null)
            }
            className="w-full rounded-md border border-border dark:border-border bg-card dark:bg-muted px-2 py-1.5 text-sm"
            disabled={usersLoading}
          >
            <option value="">— wybierz —</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name} ({u.email})
              </option>
            ))}
          </select>
          {usersLoading && (
            <span className="text-xs text-muted-foreground inline-flex items-center gap-1">
              <Loader2 className="w-3 h-3 animate-spin" /> Ładuję listę…
            </span>
          )}
        </div>
      )}

      {recipientType === "role" && (
        <div className="space-y-1">
          <label className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground">
            Rola
          </label>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="w-full rounded-md border border-border dark:border-border bg-card dark:bg-muted px-2 py-1.5 text-sm"
          >
            <option value="">— wybierz —</option>
            {ROLE_OPTIONS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="flex items-center gap-4 pt-1">
        <label className="inline-flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={notifyInapp}
            onChange={(e) => setNotifyInapp(e.target.checked)}
            className="rounded"
          />
          In-app
        </label>
        <label className="inline-flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={notifyEmail}
            onChange={(e) => setNotifyEmail(e.target.checked)}
            className="rounded"
          />
          Email
        </label>
        <label className="inline-flex items-center gap-2 text-sm ml-auto">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => setIsActive(e.target.checked)}
            className="rounded"
          />
          Aktywna
        </label>
      </div>

      {error && (
        <p className="text-xs text-destructive bg-destructive/10 dark:bg-destructive/15 border border-destructive/20 dark:border-red-700 rounded px-2 py-1">
          {error}
        </p>
      )}

      <div className="flex items-center gap-2 pt-1">
        <button
          onClick={handleSave}
          disabled={saving}
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md bg-primary text-white text-sm hover:bg-primary/90 disabled:opacity-50"
        >
          {saving ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Save className="w-3.5 h-3.5" />
          )}
          {saveLabel}
        </button>
        <button
          onClick={onCancel}
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md border border-border dark:border-border text-sm hover:bg-muted dark:hover:bg-muted"
        >
          <X className="w-3.5 h-3.5" />
          Anuluj
        </button>
      </div>
    </div>
  );
}

export { RECIPIENT_LABELS };
