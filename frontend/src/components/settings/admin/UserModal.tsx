"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  AdminUser,
  UserFormData,
  ROLES,
  RECRUITER_ROLES,
  ROLE_LABELS,
  RECRUITER_ROLE_LABELS,
  isExclusiveRole,
} from "./types";

interface UserModalProps {
  initial?: Partial<AdminUser> | null;
  onClose: () => void;
  onSave: (data: UserFormData) => void;
  loading: boolean;
  /** Odmowa serwera (np. domena spoza firmy, duplikat adresu) — UAT M11-B10.
   *  Bez niej nieudany zapis zostawiał formularz otwarty bez słowa. */
  error?: string | null;
}

export function UserModal({ initial, onClose, onSave, loading, error }: UserModalProps) {
  const isEdit = !!initial?.id;
  const initialPrimary = initial?.role ?? "recruiter";
  const rawInitialRoles =
    initial?.roles && initial.roles.length > 0
      ? initial.roles
      : initial?.role
        ? [initial.role]
        : ["recruiter"];
  const initialRoles = isExclusiveRole(initialPrimary)
    ? [initialPrimary]
    : Array.from(
        new Set([
          initialPrimary,
          ...rawInitialRoles.filter((role) => !isExclusiveRole(role)),
        ]),
      );
  const [form, setForm] = useState<UserFormData>({
    name: initial?.name ?? "",
    email: initial?.email ?? "",
    password: "",
    role: initialPrimary,
    roles: initialRoles,
    recruiter_role: initial?.recruiter_role ?? "",
    can_delete_clients: initial?.can_delete_clients ?? false,
    clear_microsoft_identity: false,
  });

  const set = <K extends keyof UserFormData>(field: K, value: UserFormData[K]) =>
    setForm((f) => ({ ...f, [field]: value }));

  const setPrimaryRole = (role: string) => {
    setForm((f) => {
      if (isExclusiveRole(role)) {
        return { ...f, role, roles: [role], recruiter_role: "" };
      }
      const withoutExclusive = f.roles.filter(
        (value) => !isExclusiveRole(value),
      );
      return {
        ...f,
        role,
        roles: withoutExclusive.includes(role)
          ? withoutExclusive
          : [role, ...withoutExclusive],
      };
    });
  };

  const toggleSecondaryRole = (role: string) => {
    setForm((f) => {
      if (isExclusiveRole(f.role) || isExclusiveRole(role)) {
        return f;
      }
      const has = f.roles.includes(role);
      const next = has ? f.roles.filter((r) => r !== role) : [...f.roles, role];
      if (!next.includes(f.role)) next.unshift(f.role);
      return { ...f, roles: next };
    });
  };

  useEffect(() => {
    setForm((f) => {
      if (f.roles.includes(f.role)) return f;
      return { ...f, roles: [f.role, ...f.roles] };
    });
  }, [form.role]);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-card rounded-xl shadow-2xl w-full max-w-md p-4 sm:p-6 space-y-5 max-h-[90dvh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            {isEdit ? "Edytuj użytkownika" : "Dodaj użytkownika"}
          </h2>
          <button onClick={onClose} aria-label="Zamknij" className="hit-area text-muted-foreground hover:text-muted-foreground dark:text-muted-foreground">
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
              className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
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
                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
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
                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
                placeholder="••••••••"
              />
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Rola podstawowa</label>
            <select
              value={form.role}
              onChange={(e) => setPrimaryRole(e.target.value)}
              className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
            >
              {ROLES.filter((r) => r !== "user").map((r) => (
                <option key={r} value={r}>{ROLE_LABELS[r] ?? r}</option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground mt-1">
              Określa domyślny widok dashboardu i wpisana jest do tokenu JWT.
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Dodatkowe role</label>
            <div className="space-y-1.5 border border-border rounded-lg px-3 py-2 max-h-44 overflow-y-auto">
              {ROLES.filter((r) => r !== "user" || r === form.role).map((r) => {
                const isPrimary = r === form.role;
                const checked = form.roles.includes(r);
                const primaryIsExclusive = isExclusiveRole(form.role);
                const roleIsExclusive = isExclusiveRole(r);
                const exclusiveConflict =
                  (primaryIsExclusive && r !== form.role) ||
                  (!primaryIsExclusive && roleIsExclusive);
                return (
                  <label
                    key={r}
                    className={cn(
                      "flex items-center gap-2 text-sm",
                      isPrimary && "text-muted-foreground italic"
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={checked || isPrimary}
                      disabled={isPrimary || exclusiveConflict}
                      onChange={() => toggleSecondaryRole(r)}
                      className="rounded border-border"
                    />
                    <span>{ROLE_LABELS[r] ?? r}</span>
                    {isPrimary && <span className="text-xs">(podstawowa)</span>}
                  </label>
                );
              })}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Osobom z kilkoma rolami (np. DL+TAC) zaznacz obie. Rola podstawowa
              jest zawsze wybrana. Finanse, Praktykant i Viewer (legacy) są rolami
              wyłącznymi i nie mogą być łączone z innymi; Viewer nie jest
              dostępny jako rola dodatkowa.
            </p>
          </div>

          {isEdit && (
            <div className="border border-border rounded-lg px-3 py-2">
              <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                <input
                  type="checkbox"
                  checked={form.can_delete_clients}
                  onChange={(e) => set("can_delete_clients", e.target.checked)}
                  className="rounded border-border"
                />
                Może usuwać klientów
              </label>
              <p className="text-xs text-muted-foreground mt-1">
                Uprawnienie imienne — nie wynika z roli (także administrator go
                nie ma bez zaznaczenia). Nadanie i odebranie trafia do Historii
                zdarzeń.
              </p>
            </div>
          )}

          {isEdit && (
            <div className="border border-border rounded-lg px-3 py-2">
              <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                <input
                  type="checkbox"
                  checked={form.clear_microsoft_identity}
                  onChange={(e) =>
                    set("clear_microsoft_identity", e.target.checked)
                  }
                  className="rounded border-border"
                />
                Odepnij tożsamość Microsoft
              </label>
              <p className="text-xs text-muted-foreground mt-1">
                Tylko gdy logowanie kończy się błędem „przypisane do innej
                tożsamości Microsoft” (np. konto odtworzone w Entra). Następne
                logowanie przypnie konto Microsoft osoby, która się zaloguje —
                upewnij się, że to właściwa osoba.
              </p>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Rola rekrutacyjna (legacy)</label>
            <select
              value={form.recruiter_role}
              onChange={(e) => set("recruiter_role", e.target.value)}
              className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
            >
              {RECRUITER_ROLES.map((r) => (
                <option key={r} value={r}>{RECRUITER_ROLE_LABELS[r] ?? r}</option>
              ))}
            </select>
          </div>
        </div>

        {error && (
          <p role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        )}

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

export default UserModal;
