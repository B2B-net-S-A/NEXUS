"use client";

import { useState, useRef, useEffect } from "react";
import { useAuthStore } from "@/store/auth";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import {
  User,
  Mail,
  Shield,
  Clock,
  Calendar,
  Lock,
  Camera,
  Eye,
  EyeOff,
  CheckCircle,
  AlertCircle,
  BarChart3,
  FileText,
  UserPlus,
  Briefcase,
} from "lucide-react";

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  try {
    return new Intl.DateTimeFormat("pl-PL", {
      day: "2-digit",
      month: "long",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(dateStr));
  } catch {
    return dateStr;
  }
}

function formatDateShort(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  try {
    return new Intl.DateTimeFormat("pl-PL", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    }).format(new Date(dateStr));
  } catch {
    return dateStr;
  }
}

function Input({
  label,
  type = "text",
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  const [show, setShow] = useState(false);
  const isPassword = type === "password";

  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
        {label}
      </label>
      <div className="relative">
        <input
          type={isPassword ? (show ? "text" : "password") : type}
          {...props}
          className="h-10 w-full px-3 text-sm border border-gray-200 dark:border-gray-600 rounded-lg
                     focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-gray-700
                     dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500
                     focus-visible:ring-2 focus-visible:ring-blue-500 pr-10"
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setShow(s => !s)}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 rounded"
            aria-label={show ? "Ukryj hasło" : "Pokaż hasło"}
          >
            {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Activity summary ──────────────────────────────────────────────────────────

const ACTIVITY_ICONS: Record<string, React.ReactNode> = {
  candidate_added: <UserPlus className="w-4 h-4 text-green-500" aria-hidden="true" />,
  job_added: <Briefcase className="w-4 h-4 text-blue-500" aria-hidden="true" />,
  note_added: <FileText className="w-4 h-4 text-yellow-500" aria-hidden="true" />,
  status_changed: <BarChart3 className="w-4 h-4 text-purple-500" aria-hidden="true" />,
};

const ACTIVITY_LABELS: Record<string, string> = {
  candidate_added: "Dodanych kandydatów",
  job_added: "Dodanych ofert",
  note_added: "Dodanych notatek",
  status_changed: "Zmiany statusu",
};

function ActivityCard({ type, count }: { type: string; count: number }) {
  return (
    <div className="flex items-center gap-3 p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
      <div className="w-8 h-8 rounded-full bg-white dark:bg-gray-800 flex items-center justify-center shadow-sm flex-shrink-0">
        {ACTIVITY_ICONS[type] ?? <BarChart3 className="w-4 h-4 text-gray-400" />}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs text-gray-500 dark:text-gray-400 leading-tight">
          {ACTIVITY_LABELS[type] ?? type}
        </p>
        <p className="text-lg font-bold text-gray-900 dark:text-gray-100 leading-tight">{count}</p>
      </div>
    </div>
  );
}

// ── Profile page ──────────────────────────────────────────────────────────────

export default function ProfilePage() {
  const { user } = useAuthStore();

  // Password form state
  const [pwForm, setPwForm] = useState({ current: "", next: "", confirm: "" });
  const [pwSaving, setPwSaving] = useState(false);
  const [pwError, setPwError] = useState("");
  const [pwSuccess, setPwSuccess] = useState(false);

  // Avatar state
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Fetch full user profile
  const { data: profile } = useQuery({
    queryKey: ["user-profile"],
    queryFn: () => api.get("/api/auth/me").then(r => r.data),
    enabled: !!user,
  });

  // Fetch activity stats (30 days)
  const { data: activityStats } = useQuery({
    queryKey: ["activity-stats-profile"],
    queryFn: () =>
      api.get("/api/activities/stats", { params: { user_id: user?.id, period: "30d" } })
        .then(r => r.data)
        .catch(() => null),
    enabled: !!user,
  });

  // Handle avatar file selection
  const handleAvatarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      setAvatarUrl(ev.target?.result as string);
    };
    reader.readAsDataURL(file);
  };

  // Handle password change
  const handlePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setPwError("");
    setPwSuccess(false);

    if (!pwForm.current) { setPwError("Podaj aktualne hasło"); return; }
    if (pwForm.next.length < 8) { setPwError("Nowe hasło musi mieć minimum 8 znaków"); return; }
    if (pwForm.next !== pwForm.confirm) { setPwError("Hasła nie są identyczne"); return; }

    setPwSaving(true);
    try {
      await api.post("/api/auth/change-password", {
        current_password: pwForm.current,
        new_password: pwForm.next,
      });
      setPwSuccess(true);
      setPwForm({ current: "", next: "", confirm: "" });
    } catch (err: any) {
      setPwError(err?.response?.data?.detail || "Błąd zmiany hasła");
    } finally {
      setPwSaving(false);
    }
  };

  const displayName = profile?.name || user?.name || "—";
  const displayEmail = profile?.email || user?.email || "—";
  const displayRole = profile?.role || user?.role || "—";

  const initials = displayName
    .split(" ")
    .map((w: string) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  // Build activity items
  const activityItems: { type: string; count: number }[] = activityStats
    ? Object.entries(activityStats).map(([type, count]) => ({ type, count: Number(count) }))
    : [];

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Profil użytkownika</h1>

      {/* Profile card */}
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm border border-gray-100 dark:border-gray-700 p-6">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-4">Informacje o koncie</h2>

        <div className="flex items-start gap-6">
          {/* Avatar */}
          <div className="flex-shrink-0">
            <div className="relative group">
              {avatarUrl ? (
                <img
                  src={avatarUrl}
                  alt={`Zdjęcie profilowe: ${displayName}`}
                  className="w-20 h-20 rounded-full object-cover ring-2 ring-blue-500"
                />
              ) : (
                <div
                  className="w-20 h-20 rounded-full bg-blue-600 flex items-center justify-center text-2xl font-bold text-white ring-2 ring-blue-500"
                  aria-label={`Inicjały: ${initials}`}
                >
                  {initials}
                </div>
              )}
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                aria-label="Zmień zdjęcie profilowe"
                className="absolute inset-0 rounded-full bg-black/50 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity focus:outline-none focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-blue-400 rounded-full"
              >
                <Camera className="w-6 h-6 text-white" aria-hidden="true" />
              </button>
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                className="hidden"
                aria-label="Wybierz zdjęcie profilowe"
                onChange={handleAvatarChange}
              />
            </div>
            <p className="text-center text-xs text-gray-400 mt-1 cursor-pointer hover:text-blue-400 transition-colors" onClick={() => fileRef.current?.click()}>
              Zmień
            </p>
          </div>

          {/* Info grid */}
          <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="flex items-start gap-2">
              <User className="w-4 h-4 text-gray-400 mt-0.5 flex-shrink-0" aria-hidden="true" />
              <div>
                <p className="text-xs text-gray-500 dark:text-gray-400">Imię i nazwisko</p>
                <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">{displayName}</p>
              </div>
            </div>
            <div className="flex items-start gap-2">
              <Mail className="w-4 h-4 text-gray-400 mt-0.5 flex-shrink-0" aria-hidden="true" />
              <div>
                <p className="text-xs text-gray-500 dark:text-gray-400">Email</p>
                <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 break-all">{displayEmail}</p>
              </div>
            </div>
            <div className="flex items-start gap-2">
              <Shield className="w-4 h-4 text-gray-400 mt-0.5 flex-shrink-0" aria-hidden="true" />
              <div>
                <p className="text-xs text-gray-500 dark:text-gray-400">Rola</p>
                <span className="inline-block text-xs px-2 py-0.5 rounded-full font-medium bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 capitalize">
                  {displayRole}
                </span>
              </div>
            </div>
            <div className="flex items-start gap-2">
              <Clock className="w-4 h-4 text-gray-400 mt-0.5 flex-shrink-0" aria-hidden="true" />
              <div>
                <p className="text-xs text-gray-500 dark:text-gray-400">Ostatnie logowanie</p>
                <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                  {formatDate(profile?.last_login)}
                </p>
              </div>
            </div>
            <div className="flex items-start gap-2">
              <Calendar className="w-4 h-4 text-gray-400 mt-0.5 flex-shrink-0" aria-hidden="true" />
              <div>
                <p className="text-xs text-gray-500 dark:text-gray-400">Konto utworzone</p>
                <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                  {formatDateShort(profile?.created_at)}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Activity summary */}
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm border border-gray-100 dark:border-gray-700 p-6">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-4">
          Twoja aktywność (30 dni)
        </h2>

        {activityItems.length > 0 ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {activityItems.map(({ type, count }) => (
              <ActivityCard key={type} type={type} count={count} />
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-10 text-gray-400 dark:text-gray-500">
            <BarChart3 className="w-12 h-12 mb-3 opacity-30" aria-hidden="true" />
            <p className="text-sm font-medium">Brak danych aktywności</p>
            <p className="text-xs mt-1">Dane pojawią się po pierwszej aktywności</p>
          </div>
        )}
      </div>

      {/* Change password */}
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm border border-gray-100 dark:border-gray-700 p-6">
        <div className="flex items-center gap-2 mb-4">
          <Lock className="w-5 h-5 text-gray-400" aria-hidden="true" />
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Zmień hasło</h2>
        </div>

        <form onSubmit={handlePasswordSubmit} className="space-y-4 max-w-md" aria-label="Formularz zmiany hasła">
          <Input
            label="Aktualne hasło"
            type="password"
            value={pwForm.current}
            onChange={e => setPwForm(f => ({ ...f, current: e.target.value }))}
            placeholder="••••••••"
            autoComplete="current-password"
          />
          <Input
            label="Nowe hasło"
            type="password"
            value={pwForm.next}
            onChange={e => setPwForm(f => ({ ...f, next: e.target.value }))}
            placeholder="Minimum 8 znaków"
            autoComplete="new-password"
          />
          <Input
            label="Potwierdź nowe hasło"
            type="password"
            value={pwForm.confirm}
            onChange={e => setPwForm(f => ({ ...f, confirm: e.target.value }))}
            placeholder="Powtórz nowe hasło"
            autoComplete="new-password"
          />

          {pwError && (
            <div
              role="alert"
              className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/30 rounded-lg px-4 py-2"
            >
              <AlertCircle className="w-4 h-4 flex-shrink-0" aria-hidden="true" />
              {pwError}
            </div>
          )}

          {pwSuccess && (
            <div
              role="status"
              className="flex items-center gap-2 text-sm text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/30 rounded-lg px-4 py-2"
            >
              <CheckCircle className="w-4 h-4 flex-shrink-0" aria-hidden="true" />
              Hasło zostało zmienione pomyślnie
            </div>
          )}

          <button
            type="submit"
            disabled={pwSaving}
            className="h-10 px-4 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white rounded-lg text-sm font-medium transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2"
            aria-label="Zapisz nowe hasło"
          >
            {pwSaving ? "Zapisywanie…" : "Zmień hasło"}
          </button>
        </form>
      </div>
    </div>
  );
}
