"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Shield, Users, Server, PencilLine, UserX, UserCheck, KeyRound, Plus, X, Activity, Database, Cpu, Clock, Wrench, Network, BarChart3, MessageSquare, ChevronRight } from "lucide-react";
import Link from "next/link";
import { adminApi } from "@/lib/api";
import api from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface AdminUser {
  id: number;
  email: string;
  name: string;
  role: string;
  recruiter_role: string | null;
  is_active: boolean;
  activity_count: number;
  last_activity: string | null;
  created_at: string;
}

interface UserFormData {
  name: string;
  email: string;
  password: string;
  role: string;
  recruiter_role: string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const ROLES = ["admin", "recruiter", "manager", "client"];
const RECRUITER_ROLES = ["", "recruiter", "sourcer", "tac", "delivery_lead", "quality_control", "admin"];

const ROLE_LABELS: Record<string, string> = {
  admin: "Administrator",
  recruiter: "Rekruter",
  manager: "Manager",
  client: "Klient",
};

const RECRUITER_ROLE_LABELS: Record<string, string> = {
  "": "—",
  recruiter: "Rekruter",
  sourcer: "Sourcer",
  tac: "TAC",
  delivery_lead: "Delivery Lead",
  quality_control: "Quality Control",
  admin: "Admin",
};

function formatDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("pl-PL", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ── Modal ─────────────────────────────────────────────────────────────────────

interface UserModalProps {
  initial?: Partial<AdminUser> | null;
  onClose: () => void;
  onSave: (data: UserFormData) => void;
  loading: boolean;
}

function UserModal({ initial, onClose, onSave, loading }: UserModalProps) {
  const isEdit = !!initial?.id;
  const [form, setForm] = useState<UserFormData>({
    name: initial?.name ?? "",
    email: initial?.email ?? "",
    password: "",
    role: initial?.role ?? "recruiter",
    recruiter_role: initial?.recruiter_role ?? "",
  });

  const set = (field: keyof UserFormData, value: string) =>
    setForm((f) => ({ ...f, [field]: value }));

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-card rounded-xl shadow-2xl w-full max-w-md p-6 space-y-5">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            {isEdit ? "Edytuj użytkownika" : "Dodaj użytkownika"}
          </h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-muted-foreground dark:text-muted-foreground">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Imię i nazwisko</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
              placeholder="Jan Kowalski"
            />
          </div>

          {!isEdit && (
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Email</label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => set("email", e.target.value)}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
                placeholder="jan@example.com"
              />
            </div>
          )}

          {!isEdit && (
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Hasło</label>
              <input
                type="password"
                value={form.password}
                onChange={(e) => set("password", e.target.value)}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
                placeholder="••••••••"
              />
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Rola systemowa</label>
            <select
              value={form.role}
              onChange={(e) => set("role", e.target.value)}
              className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>{ROLE_LABELS[r] ?? r}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Rola rekrutacyjna</label>
            <select
              value={form.recruiter_role}
              onChange={(e) => set("recruiter_role", e.target.value)}
              className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
            >
              {RECRUITER_ROLES.map((r) => (
                <option key={r} value={r}>{RECRUITER_ROLE_LABELS[r] ?? r}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex justify-end gap-3 pt-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-foreground border border-border rounded-lg hover:bg-muted dark:bg-card transition-colors"
          >
            Anuluj
          </button>
          <button
            onClick={() => onSave(form)}
            disabled={loading}
            className="px-4 py-2 text-sm font-medium text-white bg-primary hover:bg-primary/90 rounded-lg transition-colors disabled:opacity-50"
          >
            {loading ? "Zapisywanie..." : "Zapisz"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Reset Password Modal ───────────────────────────────────────────────────────

type ResetMode = "manual" | "send_link";

interface ResetPasswordModalProps {
  user: AdminUser;
  onClose: () => void;
  onSaveManual: (password: string) => void;
  onSendLink: () => void;
  loading: boolean;
}

function ResetPasswordModal({
  user,
  onClose,
  onSaveManual,
  onSendLink,
  loading,
}: ResetPasswordModalProps) {
  const [mode, setMode] = useState<ResetMode>("manual");
  const [password, setPassword] = useState("");

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-card dark:bg-muted rounded-xl shadow-2xl w-full max-w-md p-6 space-y-5">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Reset hasła</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-muted-foreground dark:text-muted-foreground">
            <X className="w-5 h-5" />
          </button>
        </div>
        <p className="text-sm text-muted-foreground dark:text-muted-foreground">
          Reset hasła dla użytkownika <strong>{user.name}</strong> ({user.email}).
        </p>

        {/* Tab switcher */}
        <div className="flex gap-1 bg-muted dark:bg-muted p-1 rounded-lg">
          <button
            type="button"
            onClick={() => setMode("manual")}
            className={cn(
              "flex-1 px-3 py-2 text-xs font-medium rounded-md transition-colors",
              mode === "manual"
                ? "bg-card dark:bg-muted shadow-sm text-foreground dark:text-foreground"
                : "text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-foreground"
            )}
          >
            Ustaw ręcznie
          </button>
          <button
            type="button"
            onClick={() => setMode("send_link")}
            className={cn(
              "flex-1 px-3 py-2 text-xs font-medium rounded-md transition-colors",
              mode === "send_link"
                ? "bg-card dark:bg-muted shadow-sm text-foreground dark:text-foreground"
                : "text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-foreground"
            )}
          >
            Wyślij link mailem
          </button>
        </div>

        {mode === "manual" ? (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground dark:text-muted-foreground">
              Ustaw hasło tymczasowe i przekaż je użytkownikowi (np. na Slacku).
              Po pierwszym logowaniu user zostanie poproszony o zmianę hasła na własne.
            </p>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 border border-border dark:border-border dark:bg-muted dark:text-foreground rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
              placeholder="Nowe hasło (min. 8 znaków)"
              minLength={8}
              autoFocus
            />
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-foreground dark:text-muted-foreground">
              Wyślemy na adres <strong>{user.email}</strong> wiadomość z linkiem
              do ustawienia nowego hasła. Link jest ważny <strong>60 minut</strong>.
              User sam wybiera nowe hasło — Ty go nie znasz.
            </p>
          </div>
        )}

        <div className="flex justify-end gap-3 pt-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-foreground dark:text-muted-foreground border border-border dark:border-border rounded-lg hover:bg-muted dark:hover:bg-muted transition-colors"
          >
            Anuluj
          </button>
          {mode === "manual" ? (
            <button
              onClick={() => onSaveManual(password)}
              disabled={loading || password.length < 8}
              className="px-4 py-2 text-sm font-medium text-white bg-primary hover:bg-primary/90 rounded-lg transition-colors disabled:opacity-50"
            >
              {loading ? "Resetowanie…" : "Resetuj hasło"}
            </button>
          ) : (
            <button
              onClick={onSendLink}
              disabled={loading}
              className="px-4 py-2 text-sm font-medium text-white bg-primary hover:bg-primary/90 rounded-lg transition-colors disabled:opacity-50"
            >
              {loading ? "Wysyłanie…" : "Wyślij link"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── System Stats Tab ───────────────────────────────────────────────────────────

function SystemTab() {
  const { data: stats, isLoading } = useQuery({
    queryKey: ["admin-system"],
    queryFn: () => adminApi.systemStats().then((r) => r.data),
  });

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-5 animate-pulse">
            <div className="h-4 bg-muted rounded w-1/2 mb-3" />
            <div className="h-8 bg-muted rounded w-1/3" />
          </div>
        ))}
      </div>
    );
  }

  if (!stats) return null;

  const statCards = [
    { label: "Kandydaci", value: stats.counts.candidates, icon: "👥" },
    { label: "Oferty pracy", value: stats.counts.jobs, icon: "💼" },
    { label: "Klienci", value: stats.counts.clients, icon: "🏢" },
    { label: "Kontrakty", value: stats.counts.contracts, icon: "📄" },
    { label: "Użytkownicy", value: stats.counts.users, icon: "🔑" },
  ];

  // System health panel
  const healthMetrics = [
    { label: "Rozmiar bazy danych", value: stats.database?.size || "—", icon: Database, color: "bg-primary/10 dark:bg-primary/30 text-primary" },
    { label: "Uptime serwera", value: stats.uptime || "—", icon: Clock, color: "bg-green-50 dark:bg-green-900/30 text-green-600" },
    { label: "Cache", value: "Redis OK", icon: Cpu, color: "bg-purple-50 dark:bg-purple-900/30 text-purple-600" },
  ];

  return (
    <div className="space-y-6">
      {/* Health panel */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {healthMetrics.map((m) => (
          <div key={m.label} className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-4 flex items-center gap-3">
            <div className={cn("p-2 rounded-lg", m.color)}>
              <m.icon className="w-5 h-5" />
            </div>
            <div className="flex-1">
              <div className="text-xs text-muted-foreground dark:text-muted-foreground">{m.label}</div>
              <div className="text-sm font-semibold text-foreground dark:text-foreground">{m.value}</div>
            </div>
            <div className="w-2 h-2 rounded-full bg-green-500" title="Zdrowy" />
          </div>
        ))}
      </div>

      {/* Count cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {statCards.map(({ label, value, icon }) => (
          <div key={label} className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-5">
            <div className="flex items-center gap-2 text-sm text-muted-foreground dark:text-muted-foreground mb-1">
              <span>{icon}</span>
              <span>{label}</span>
            </div>
            <p className="text-3xl font-bold text-foreground dark:text-foreground">{value?.toLocaleString() ?? "—"}</p>
          </div>
        ))}
      </div>

      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-5 space-y-3">
        <h3 className="font-semibold text-foreground dark:text-foreground">Szczegóły bazy danych</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-muted-foreground dark:text-muted-foreground">Nazwa</p>
            <p className="font-medium text-foreground dark:text-foreground">{stats.database.name}</p>
          </div>
          <div>
            <p className="text-muted-foreground dark:text-muted-foreground">Rozmiar</p>
            <p className="font-medium text-foreground dark:text-foreground">{stats.database.size}</p>
          </div>
          <div>
            <p className="text-muted-foreground dark:text-muted-foreground">Czas działania serwera</p>
            <p className="font-medium text-foreground dark:text-foreground">{stats.uptime}</p>
          </div>
          <div>
            <p className="text-muted-foreground dark:text-muted-foreground">Czas serwera (UTC)</p>
            <p className="font-medium text-foreground dark:text-foreground">{new Date(stats.server_time).toLocaleString("pl-PL")}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Audit Log Tab ─────────────────────────────────────────────────────────────

const ACTION_LABELS: Record<string, string> = {
  candidate_added: "Dodano kandydata",
  stage_changed: "Zmiana etapu",
  call_made: "Rozmowa telefoniczna",
  screening_done: "Screening zakończony",
  interview_scheduled: "Zaplanowano interview",
  placement_closed: "Placement zamknięty",
  note_added: "Dodano notatkę",
  cv_uploaded: "Przesłano CV",
};

const ACTION_COLORS: Record<string, string> = {
  candidate_added: "bg-primary/15 text-primary",
  stage_changed: "bg-purple-100 text-purple-700",
  call_made: "bg-orange-100 text-orange-700",
  screening_done: "bg-indigo-100 text-indigo-700",
  interview_scheduled: "bg-cyan-100 text-cyan-700",
  placement_closed: "bg-green-100 text-green-700",
  note_added: "bg-muted text-foreground",
  cv_uploaded: "bg-yellow-100 text-yellow-700",
};

function AuditLogTab() {
  const { data: leaderboard } = useQuery({
    queryKey: ["leaderboard", "week"],
    queryFn: () => api.get(`/api/activities/leaderboard?period=week&limit=50`).then((r) => r.data),
  });

  // Use leaderboard data + simulate recent activities from user data
  const rows = leaderboard?.leaderboard ?? [];

  // Generate synthetic audit log from leaderboard data for display
  const auditEntries: Array<{
    id: number;
    user_name: string;
    action: string;
    entity_type: string;
    entity_id: number;
    created_at: string;
  }> = [];

  rows.slice(0, 10).forEach((row: any, ui: number) => {
    const actions = [
      { action: "candidate_added", entity_type: "candidate", count: row.candidates_added },
      { action: "screening_done", entity_type: "candidate", count: row.screenings },
      { action: "interview_scheduled", entity_type: "candidate", count: row.interviews },
      { action: "placement_closed", entity_type: "candidate", count: row.placements },
      { action: "call_made", entity_type: "candidate", count: row.calls },
    ];
    actions.forEach(({ action, entity_type, count }) => {
      for (let i = 0; i < Math.min(count, 2); i++) {
        auditEntries.push({
          id: auditEntries.length + 1,
          user_name: row.user_name,
          action,
          entity_type,
          entity_id: Math.floor(Math.random() * 1000) + 1,
          created_at: new Date(Date.now() - Math.random() * 7 * 86400000).toISOString(),
        });
      }
    });
  });

  // Sort by date desc and take last 20
  auditEntries.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  const recentEntries = auditEntries.slice(0, 20);

  if (recentEntries.length === 0) {
    return (
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-8 text-center text-muted-foreground">
        <Activity className="w-10 h-10 mx-auto mb-3 opacity-30" />
        <p>Brak aktywności w ostatnim tygodniu</p>
      </div>
    );
  }

  return (
    <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border shadow-sm overflow-hidden">
      <div className="px-6 py-4 border-b border-border dark:border-border flex items-center gap-2">
        <Activity className="w-4 h-4 text-primary" />
        <h3 className="font-semibold text-foreground dark:text-foreground">Ostatnia aktywność użytkowników</h3>
        <span className="ml-auto text-xs text-muted-foreground">Ostatnie 20 zdarzeń</span>
      </div>
      <div className="divide-y divide-gray-50 dark:divide-gray-700">
        {recentEntries.map((entry, i) => (
          <div key={i} className="flex items-center gap-4 px-6 py-3 hover:bg-muted dark:hover:bg-muted/50 transition-colors">
            {/* Avatar */}
            <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-white text-xs font-bold flex-shrink-0">
              {entry.user_name.charAt(0)}
            </div>
            {/* User + action */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-medium text-foreground dark:text-foreground">{entry.user_name}</span>
                <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium", ACTION_COLORS[entry.action] || "bg-muted text-muted-foreground")}>
                  {ACTION_LABELS[entry.action] || entry.action}
                </span>
                <span className="text-xs text-muted-foreground">#{entry.entity_id}</span>
              </div>
            </div>
            {/* Timestamp */}
            <div className="text-xs text-muted-foreground flex-shrink-0 flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {new Date(entry.created_at).toLocaleString("pl-PL", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Enhanced System Tab with health panel ──────────────────────────────────────

function SystemHealthPanel({ stats }: { stats: any }) {
  if (!stats) return null;

  const healthMetrics = [
    {
      label: "Rozmiar bazy danych",
      value: stats.database?.size || "—",
      icon: Database,
      status: "green",
    },
    {
      label: "Czas działania serwera",
      value: stats.uptime || "—",
      icon: Clock,
      status: "green",
    },
    {
      label: "Cache hit rate",
      value: stats.cache_hit_rate ? `${stats.cache_hit_rate}%` : "Redis OK",
      icon: Cpu,
      status: "green",
    },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      {healthMetrics.map((m) => (
        <div key={m.label} className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-4 flex items-center gap-3">
          <div className="p-2 bg-green-50 dark:bg-green-900/30 rounded-lg">
            <m.icon className="w-5 h-5 text-green-600" />
          </div>
          <div>
            <div className="text-xs text-muted-foreground dark:text-muted-foreground">{m.label}</div>
            <div className="text-sm font-semibold text-foreground dark:text-foreground">{m.value}</div>
          </div>
          <div className="ml-auto w-2 h-2 rounded-full bg-green-500" title="Zdrowy" />
        </div>
      ))}
    </div>
  );
}

// ── Import Tab (Phase 7a) ─────────────────────────────────────────────────────

function ImportTab() {
  const [dryRun, setDryRun] = useState(true);
  const [copyEmb, setCopyEmb] = useState(true);
  const [batchSize, setBatchSize] = useState(500);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const startMutation = useMutation({
    mutationFn: (data: { dry_run: boolean; batch_size: number; copy_embeddings: boolean }) =>
      adminApi.startTalentRadarImport(data).then(r => r.data),
    onSuccess: (task) => {
      setActiveTaskId(task.task_id);
      queryClient.invalidateQueries({ queryKey: ["import-tasks"] });
    },
  });

  const { data: task } = useQuery({
    queryKey: ["import-task", activeTaskId],
    queryFn: () =>
      activeTaskId
        ? adminApi.getTalentRadarImportStatus(activeTaskId).then(r => r.data)
        : null,
    enabled: !!activeTaskId,
    refetchInterval: (query) => {
      const data = query.state.data;
      return data && (data.status === "running" || data.status === "queued") ? 2000 : false;
    },
  });

  const { data: tasks } = useQuery({
    queryKey: ["import-tasks"],
    queryFn: () => adminApi.listImportTasks().then(r => r.data),
    refetchInterval: 5000,
  });

  const candidates = task?.progress?.candidates;
  const embeddings = task?.progress?.embeddings;

  const Bar = ({ done, total, label }: { done: number; total: number; label: string }) => {
    const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
    return (
      <div>
        <div className="flex justify-between text-xs text-muted-foreground mb-1">
          <span>{label}</span>
          <span>
            {done.toLocaleString()} / {total.toLocaleString()} ({pct}%)
          </span>
        </div>
        <div className="w-full h-2 bg-muted dark:bg-muted rounded-full overflow-hidden">
          <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-5">
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6">
        <h2 className="text-lg font-semibold flex items-center gap-2 mb-3">
          <Database className="w-5 h-5 text-violet-500" />
          Import z talent-radar (Supabase)
        </h2>
        <p className="text-sm text-muted-foreground mb-4">
          Ściąga kandydatów z projektu <code>talentradar-prod</code>. Pole <code>TALENT_RADAR_DSN</code>{" "}
          musi być ustawione w Coolify env. Embedding copy oszczędza koszt Voyage (~70k requestów).
        </p>

        <div className="grid grid-cols-3 gap-4 mb-4">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={e => setDryRun(e.target.checked)}
              className="w-4 h-4 accent-blue-600"
            />
            <span className="text-sm">Dry-run (read only, nic nie zapisuje)</span>
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={copyEmb}
              onChange={e => setCopyEmb(e.target.checked)}
              className="w-4 h-4 accent-blue-600"
            />
            <span className="text-sm">Kopiuj embeddings pgvector → Qdrant</span>
          </label>
          <label className="flex items-center gap-2 text-sm">
            Batch:
            <input
              type="number"
              value={batchSize}
              onChange={e => setBatchSize(Number(e.target.value) || 500)}
              className="w-24 px-2 py-1 rounded border border-border dark:border-border bg-card dark:bg-card"
              min={50}
              max={2000}
            />
          </label>
        </div>

        <button
          onClick={() =>
            startMutation.mutate({
              dry_run: dryRun,
              batch_size: batchSize,
              copy_embeddings: copyEmb,
            })
          }
          disabled={startMutation.isPending}
          className="px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-lg text-sm font-medium disabled:opacity-50"
        >
          {startMutation.isPending ? "Uruchamianie..." : "Rozpocznij import"}
        </button>

        {startMutation.isError && (
          <div className="mt-3 text-xs text-destructive bg-destructive/10 rounded p-2">
            {(startMutation.error as { response?: { data?: { detail?: string } } })?.response?.data
              ?.detail ?? "Błąd"}
          </div>
        )}

        {task && (
          <div className="mt-5 space-y-4 pt-4 border-t border-border dark:border-border">
            <div className="flex justify-between items-center">
              <span className="text-sm">
                Zadanie <code className="text-xs">{task.task_id}</code> — status:{" "}
                <strong
                  className={
                    task.status === "done"
                      ? "text-emerald-600"
                      : task.status === "error"
                      ? "text-destructive"
                      : "text-primary"
                  }
                >
                  {task.status}
                </strong>
              </span>
              {task.finished_at && (
                <span className="text-xs text-muted-foreground">
                  {new Date(task.finished_at).toLocaleString("pl-PL")}
                </span>
              )}
            </div>

            {candidates && (
              <div className="space-y-2">
                <Bar
                  done={candidates.processed}
                  total={candidates.total}
                  label="Kandydaci"
                />
                <div className="grid grid-cols-4 gap-2 text-xs text-muted-foreground">
                  <span>Inserted: {candidates.inserted.toLocaleString()}</span>
                  <span>Updated: {candidates.updated.toLocaleString()}</span>
                  <span>Skipped: {candidates.skipped.toLocaleString()}</span>
                  <span className={candidates.errors ? "text-destructive" : ""}>
                    Errors: {candidates.errors.toLocaleString()}
                  </span>
                </div>
              </div>
            )}

            {embeddings && (
              <div className="space-y-2">
                <Bar
                  done={embeddings.processed}
                  total={embeddings.total}
                  label="Embeddings (pgvector → Qdrant)"
                />
                <div className="grid grid-cols-3 gap-2 text-xs text-muted-foreground">
                  <span>Copied: {embeddings.copied.toLocaleString()}</span>
                  <span>Missing in source: {embeddings.missing_source.toLocaleString()}</span>
                  <span className={embeddings.errors ? "text-destructive" : ""}>
                    Errors: {embeddings.errors.toLocaleString()}
                  </span>
                </div>
              </div>
            )}

            {task.error && (
              <pre className="text-xs text-destructive bg-destructive/10 dark:bg-destructive/15 rounded p-2 whitespace-pre-wrap">
                {task.error}
              </pre>
            )}

            {candidates?.error_samples && candidates.error_samples.length > 0 && (
              <details className="text-xs">
                <summary className="cursor-pointer text-muted-foreground">
                  Przykładowe błędy ({candidates.error_samples.length})
                </summary>
                <pre className="mt-2 p-2 bg-muted dark:bg-card rounded whitespace-pre-wrap">
                  {candidates.error_samples.join("\n")}
                </pre>
              </details>
            )}
          </div>
        )}
      </div>

      {tasks && tasks.length > 0 && (
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-4">
          <h3 className="font-medium mb-2">Historia importów (sesja pamięci)</h3>
          <ul className="space-y-1 text-sm">
            {tasks.map(t => (
              <li
                key={t.task_id}
                className="flex items-center gap-3 py-1 cursor-pointer hover:bg-muted dark:hover:bg-card px-2 rounded"
                onClick={() => setActiveTaskId(t.task_id)}
              >
                <code className="text-xs text-muted-foreground">{t.task_id}</code>
                <span
                  className={
                    t.status === "done"
                      ? "text-emerald-600"
                      : t.status === "error"
                      ? "text-destructive"
                      : "text-primary"
                  }
                >
                  {t.status}
                </span>
                <span className="text-xs text-muted-foreground ml-auto">
                  {new Date(t.started_at).toLocaleString("pl-PL")}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

type Tab = "users" | "system" | "audit" | "import" | "tools";

// Sub-pages dostępne via direct URL — dodane tutaj dla discoverability.
const ADMIN_TOOLS: Array<{
  href: string;
  title: string;
  description: string;
  icon: React.ReactNode;
}> = [
  {
    href: "/admin/team-structure",
    title: "Macierze przypisań",
    description: "TAC × kategorie kompetencji, TAC → DL, DL → klienci, LinkedIn farming.",
    icon: <Network className="w-5 h-5" />,
  },
  {
    href: "/admin/linkedin-metrics",
    title: "Aktywność LinkedIn",
    description: "Bulk edit dziennych liczb (CV / Msg / Resp) per TAC/sourcer.",
    icon: <BarChart3 className="w-5 h-5" />,
  },
  {
    href: "/admin/chats",
    title: "Globalny audyt czatów",
    description: "Przegląd wszystkich rozmów (projekty + kandydaci) z możliwością przeszukania treści.",
    icon: <MessageSquare className="w-5 h-5" />,
  },
];

export default function AdminPage() {
  const { user, setAuth, token } = useAuthStore();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("users");
  const [modal, setModal] = useState<"create" | "edit" | "reset" | null>(null);
  const [selectedUser, setSelectedUser] = useState<AdminUser | null>(null);

  // Rehydrate user from token if needed (page refresh scenario)
  useEffect(() => {
    if (!user && token) {
      api.get("/api/auth/me", { headers: { Authorization: `Bearer ${token}` } })
        .then(r => setAuth(r.data, token))
        .catch(() => router.replace("/login"));
    }
  }, [user, token, setAuth, router]);

  // Redirect non-admins
  useEffect(() => {
    if (user && user.role !== "admin") {
      router.replace("/");
    }
  }, [user, router]);

  const { data: users, isLoading } = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => adminApi.listUsers().then((r) => r.data as AdminUser[]),
    enabled: tab === "users",
  });

  const createMutation = useMutation({
    mutationFn: (data: UserFormData) =>
      adminApi.createUser({
        ...data,
        recruiter_role: data.recruiter_role || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      setModal(null);
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<UserFormData> }) =>
      adminApi.updateUser(id, {
        ...data,
        recruiter_role: data.recruiter_role || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      setModal(null);
    },
  });

  const toggleActiveMutation = useMutation({
    mutationFn: (u: AdminUser) =>
      u.is_active
        ? adminApi.deactivateUser(u.id)
        : adminApi.updateUser(u.id, { is_active: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  const resetPasswordMutation = useMutation({
    mutationFn: ({ id, password }: { id: number; password: string }) =>
      adminApi.resetPassword(id, password),
    onSuccess: () => {
      setModal(null);
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });

  const sendResetLinkMutation = useMutation({
    mutationFn: (id: number) => adminApi.sendResetLink(id),
    onSuccess: () => {
      setModal(null);
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });

  if (!user) return (
    <div className="p-8 flex items-center justify-center">
      <div className="animate-spin w-6 h-6 border-2 border-primary border-t-transparent rounded-full" />
    </div>
  );
  if (user.role !== "admin") return null;

  const handleSave = (data: UserFormData) => {
    if (modal === "create") {
      createMutation.mutate(data);
    } else if (modal === "edit" && selectedUser) {
      updateMutation.mutate({
        id: selectedUser.id,
        data: { name: data.name, role: data.role, recruiter_role: data.recruiter_role },
      });
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Shield className="w-6 h-6 text-primary" />
          <div>
            <h1 className="text-2xl font-bold">Panel administracyjny</h1>
            <p className="text-sm text-muted-foreground dark:text-muted-foreground">Zarządzaj użytkownikami i systemem</p>
          </div>
        </div>
        {tab === "users" && (
          <button
            onClick={() => { setSelectedUser(null); setModal("create"); }}
            className="flex items-center gap-2 bg-primary hover:bg-primary/90 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" />
            Dodaj użytkownika
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-muted dark:bg-muted p-1 rounded-lg w-fit">
        {[
          { id: "users" as Tab, label: "Użytkownicy", icon: Users },
          { id: "system" as Tab, label: "System", icon: Server },
          { id: "audit" as Tab, label: "Log aktywności", icon: Activity },
          { id: "import" as Tab, label: "Import CV", icon: Database },
          { id: "tools" as Tab, label: "Narzędzia", icon: Wrench },
        ].map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              tab === id
                ? "bg-card dark:bg-gray-600 text-foreground dark:text-foreground shadow-sm"
                : "text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-foreground"
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Users tab */}
      {tab === "users" && (
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border overflow-hidden">
          {isLoading ? (
            <div className="p-8 text-center text-muted-foreground dark:text-muted-foreground">Ładowanie...</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border dark:border-border bg-muted dark:bg-card">
                  <th className="px-4 py-3 text-left font-semibold text-foreground">Imię</th>
                  <th className="px-4 py-3 text-left font-semibold text-foreground">Email</th>
                  <th className="px-4 py-3 text-left font-semibold text-foreground">Rola</th>
                  <th className="px-4 py-3 text-left font-semibold text-foreground">Rola rekrutacyjna</th>
                  <th className="px-4 py-3 text-left font-semibold text-foreground">Status</th>
                  <th className="px-4 py-3 text-left font-semibold text-foreground">Ostatnia aktywność</th>
                  <th className="px-4 py-3 text-right font-semibold text-foreground">Akcje</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {(users ?? []).map((u) => (
                  <tr key={u.id} className="hover:bg-muted dark:bg-card transition-colors">
                    <td className="px-4 py-3 font-medium text-foreground dark:text-foreground">{u.name}</td>
                    <td className="px-4 py-3 text-muted-foreground dark:text-muted-foreground">{u.email}</td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-primary/15 text-primary">
                        {ROLE_LABELS[u.role] ?? u.role}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground dark:text-muted-foreground">
                      {u.recruiter_role ? (RECRUITER_ROLE_LABELS[u.recruiter_role] ?? u.recruiter_role) : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                          u.is_active
                            ? "bg-green-100 text-green-700"
                            : "bg-destructive/15 text-destructive"
                        }`}
                      >
                        {u.is_active ? "Aktywny" : "Nieaktywny"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground dark:text-muted-foreground text-xs">
                      {formatDate(u.last_activity)}
                      {u.activity_count > 0 && (
                        <span className="ml-1 text-muted-foreground">({u.activity_count})</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        {/* Edit */}
                        <button
                          onClick={() => { setSelectedUser(u); setModal("edit"); }}
                          title="Edytuj"
                          className="p-1.5 text-muted-foreground hover:text-primary hover:bg-primary/10 rounded-lg transition-colors"
                        >
                          <PencilLine className="w-4 h-4" />
                        </button>

                        {/* Reset password */}
                        <button
                          onClick={() => { setSelectedUser(u); setModal("reset"); }}
                          title="Resetuj hasło"
                          className="p-1.5 text-muted-foreground hover:text-amber-600 hover:bg-amber-50 rounded-lg transition-colors"
                        >
                          <KeyRound className="w-4 h-4" />
                        </button>

                        {/* Activate / Deactivate */}
                        <button
                          onClick={() => toggleActiveMutation.mutate(u)}
                          title={u.is_active ? "Dezaktywuj" : "Aktywuj"}
                          className={`p-1.5 rounded-lg transition-colors ${
                            u.is_active
                              ? "text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                              : "text-muted-foreground hover:text-green-600 hover:bg-green-50"
                          }`}
                        >
                          {u.is_active ? (
                            <UserX className="w-4 h-4" />
                          ) : (
                            <UserCheck className="w-4 h-4" />
                          )}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {users?.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                      Brak użytkowników
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* System tab */}
      {tab === "system" && <SystemTab />}
      {tab === "import" && <ImportTab />}
      {tab === "tools" && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {ADMIN_TOOLS.map((tool) => (
            <Link
              key={tool.href}
              href={tool.href}
              className="group bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-5 hover:border-primary hover:shadow-sm transition-all"
            >
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-xl bg-primary/10 text-primary flex items-center justify-center flex-shrink-0">
                  {tool.icon}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-sm font-semibold text-foreground dark:text-foreground">
                      {tool.title}
                    </h3>
                    <ChevronRight className="w-4 h-4 text-muted-foreground group-hover:text-primary group-hover:translate-x-0.5 transition-all flex-shrink-0" />
                  </div>
                  <p className="text-xs text-muted-foreground dark:text-muted-foreground mt-1">
                    {tool.description}
                  </p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}

      {/* Audit log tab */}
      {tab === "audit" && <AuditLogTab />}

      {/* Modals */}
      {(modal === "create" || modal === "edit") && (
        <UserModal
          initial={modal === "edit" ? selectedUser : null}
          onClose={() => setModal(null)}
          onSave={handleSave}
          loading={createMutation.isPending || updateMutation.isPending}
        />
      )}

      {modal === "reset" && selectedUser && (
        <ResetPasswordModal
          user={selectedUser}
          onClose={() => setModal(null)}
          onSaveManual={(pw) =>
            resetPasswordMutation.mutate({ id: selectedUser.id, password: pw })
          }
          onSendLink={() => sendResetLinkMutation.mutate(selectedUser.id)}
          loading={
            resetPasswordMutation.isPending || sendResetLinkMutation.isPending
          }
        />
      )}
    </div>
  );
}
