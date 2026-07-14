"use client";

import { useState, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { useQuery, useQueryClient } from "@tanstack/react-query";
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
  AlertTriangle,
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
      <label className="block text-xs font-medium text-muted-foreground dark:text-muted-foreground mb-1">
        {label}
      </label>
      <div className="relative">
        <input
          type={isPassword ? (show ? "text" : "password") : type}
          {...props}
          className="h-10 w-full px-3 text-sm border border-border dark:border-border rounded-lg
                     focus:outline-none focus:ring-2 focus-visible:ring-ring bg-card dark:bg-muted
                     dark:text-foreground placeholder:text-muted-foreground dark:placeholder:text-muted-foreground
                     focus-visible:ring-2 focus-visible:ring-ring pr-10"
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setShow(s => !s)}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-muted-foreground dark:hover:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
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
  job_added: <Briefcase className="w-4 h-4 text-primary" aria-hidden="true" />,
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
    <div className="flex items-center gap-3 p-3 bg-muted dark:bg-muted/50 rounded-lg">
      <div className="w-8 h-8 rounded-full bg-card dark:bg-muted flex items-center justify-center shadow-sm flex-shrink-0">
        {ACTIVITY_ICONS[type] ?? <BarChart3 className="w-4 h-4 text-muted-foreground" />}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs text-muted-foreground dark:text-muted-foreground leading-tight">
          {ACTIVITY_LABELS[type] ?? type}
        </p>
        <p className="text-lg font-bold text-foreground dark:text-foreground leading-tight">{count}</p>
      </div>
    </div>
  );
}

// ── Profile page ──────────────────────────────────────────────────────────────

export default function ProfilePage() {
  const { user } = useAuthStore();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();

  // Force-change-password gate. Pokazujemy banner gdy:
  //   - middleware przekierował tu z innego route'u (?force_password_change=1), lub
  //   - user.force_password_change=true w store (zapasowe — middleware to klucz)
  const forcedFromUrl = searchParams.get("force_password_change") === "1";
  const forcedFromStore = user?.force_password_change === true;
  const mustChangePassword = forcedFromUrl || forcedFromStore;

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

      // Zmiana hasła podnosi token_version i unieważnia wszystkie aktywne
      // sesje użytkownika. Backend wyczyścił cookies w tej odpowiedzi; lokalny
      // store kończymy po krótkim potwierdzeniu sukcesu.
      queryClient.invalidateQueries({ queryKey: ["user-profile"] });
      setTimeout(() => {
        void useAuthStore.getState().logout();
      }, 1500);
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
      <h1 className="text-2xl font-bold text-foreground dark:text-foreground">Profil użytkownika</h1>

      {/* Force-change-password banner */}
      {mustChangePassword && !pwSuccess && (
        <div
          role="alert"
          className="bg-amber-50 dark:bg-amber-900/30 border-l-4 border-amber-400 dark:border-amber-500 rounded-r-lg p-4 flex items-start gap-3"
        >
          <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" aria-hidden="true" />
          <div className="flex-1">
            <p className="font-semibold text-amber-900 dark:text-amber-200">
              Twoje hasło zostało zresetowane przez administratora
            </p>
            <p className="text-sm text-amber-800 dark:text-amber-300 mt-1">
              Aby kontynuować pracę w NEXUS, ustaw teraz nowe hasło w formularzu poniżej.
              Pozostałe sekcje aplikacji są zablokowane do czasu zmiany hasła.
            </p>
          </div>
        </div>
      )}

      {/* Profile card */}
      <div className="bg-card dark:bg-muted rounded-2xl shadow-sm border border-border dark:border-border p-6">
        <h2 className="text-xl font-semibold text-foreground dark:text-foreground mb-4">Informacje o koncie</h2>

        <div className="flex items-start gap-6">
          {/* Avatar */}
          <div className="flex-shrink-0">
            <div className="relative group">
              {avatarUrl ? (
                <img
                  src={avatarUrl}
                  alt={`Zdjęcie profilowe: ${displayName}`}
                  className="w-20 h-20 rounded-full object-cover ring-2 ring-ring"
                />
              ) : (
                <div
                  className="w-20 h-20 rounded-full bg-primary flex items-center justify-center text-2xl font-bold text-white ring-2 ring-ring"
                  aria-label={`Inicjały: ${initials}`}
                >
                  {initials}
                </div>
              )}
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                aria-label="Zmień zdjęcie profilowe"
                className="absolute inset-0 rounded-full bg-black/50 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity focus:outline-none focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring rounded-full"
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
            <p className="text-center text-xs text-muted-foreground mt-1 cursor-pointer hover:text-primary transition-colors" onClick={() => fileRef.current?.click()}>
              Zmień
            </p>
          </div>

          {/* Info grid */}
          <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="flex items-start gap-2">
              <User className="w-4 h-4 text-muted-foreground mt-0.5 flex-shrink-0" aria-hidden="true" />
              <div>
                <p className="text-xs text-muted-foreground dark:text-muted-foreground">Imię i nazwisko</p>
                <p className="text-sm font-semibold text-foreground dark:text-foreground">{displayName}</p>
              </div>
            </div>
            <div className="flex items-start gap-2">
              <Mail className="w-4 h-4 text-muted-foreground mt-0.5 flex-shrink-0" aria-hidden="true" />
              <div>
                <p className="text-xs text-muted-foreground dark:text-muted-foreground">Email</p>
                <p className="text-sm font-semibold text-foreground dark:text-foreground break-all">{displayEmail}</p>
              </div>
            </div>
            <div className="flex items-start gap-2">
              <Shield className="w-4 h-4 text-muted-foreground mt-0.5 flex-shrink-0" aria-hidden="true" />
              <div>
                <p className="text-xs text-muted-foreground dark:text-muted-foreground">Rola</p>
                <span className="inline-block text-xs px-2 py-0.5 rounded-full font-medium bg-primary/15 dark:bg-primary/10 text-primary dark:text-primary capitalize">
                  {displayRole}
                </span>
              </div>
            </div>
            <div className="flex items-start gap-2">
              <Clock className="w-4 h-4 text-muted-foreground mt-0.5 flex-shrink-0" aria-hidden="true" />
              <div>
                <p className="text-xs text-muted-foreground dark:text-muted-foreground">Ostatnia aktywność</p>
                <p className="text-sm font-semibold text-foreground dark:text-foreground">
                  {formatDate(profile?.last_seen_at)}
                </p>
              </div>
            </div>
            <div className="flex items-start gap-2">
              <Calendar className="w-4 h-4 text-muted-foreground mt-0.5 flex-shrink-0" aria-hidden="true" />
              <div>
                <p className="text-xs text-muted-foreground dark:text-muted-foreground">Konto utworzone</p>
                <p className="text-sm font-semibold text-foreground dark:text-foreground">
                  {formatDateShort(profile?.created_at)}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Activity summary */}
      <div className="bg-card dark:bg-muted rounded-2xl shadow-sm border border-border dark:border-border p-6">
        <h2 className="text-xl font-semibold text-foreground dark:text-foreground mb-4">
          Twoja aktywność (30 dni)
        </h2>

        {activityItems.length > 0 ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {activityItems.map(({ type, count }) => (
              <ActivityCard key={type} type={type} count={count} />
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-10 text-muted-foreground dark:text-muted-foreground">
            <BarChart3 className="w-12 h-12 mb-3 opacity-30" aria-hidden="true" />
            <p className="text-sm font-medium">Brak danych aktywności</p>
            <p className="text-xs mt-1">Dane pojawią się po pierwszej aktywności</p>
          </div>
        )}
      </div>

      {/* Change password */}
      <div className="bg-card dark:bg-muted rounded-2xl shadow-sm border border-border dark:border-border p-6">
        <div className="flex items-center gap-2 mb-4">
          <Lock className="w-5 h-5 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-xl font-semibold text-foreground dark:text-foreground">Zmień hasło</h2>
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
              className="flex items-center gap-2 text-sm text-destructive dark:text-destructive bg-destructive/10 dark:bg-red-900/30 rounded-lg px-4 py-2"
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
            className="h-10 px-4 bg-primary hover:bg-primary/90 disabled:opacity-60 text-white rounded-lg text-sm font-medium transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            aria-label="Zapisz nowe hasło"
          >
            {pwSaving ? "Zapisywanie…" : "Zmień hasło"}
          </button>
        </form>
      </div>
    </div>
  );
}
