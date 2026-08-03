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
} from "./types";

interface UserModalProps {
  initial?: Partial<AdminUser> | null;
  onClose: () => void;
  onSave: (data: UserFormData) => void;
  loading: boolean;
}

export function UserModal({ initial, onClose, onSave, loading }: UserModalProps) {
  const isEdit = !!initial?.id;
  const initialPrimary = initial?.role ?? "recruiter";
  const rawInitialRoles =
    initial?.roles && initial.roles.length > 0
      ? initial.roles
      : initial?.role
        ? [initial.role]
        : ["recruiter"];
  const initialRoles =
    initialPrimary === "finance" || initialPrimary === "user"
      ? [initialPrimary]
      : Array.from(
          new Set([
            initialPrimary,
            ...rawInitialRoles.filter(
              (role) => role !== "finance" && role !== "user",
            ),
          ]),
        );
  const [form, setForm] = useState<UserFormData>({
    name: initial?.name ?? "",
    email: initial?.email ?? "",
    password: "",
    role: initialPrimary,
    roles: initialRoles,
    recruiter_role: initial?.recruiter_role ?? "",
  });

  const set = <K extends keyof UserFormData>(field: K, value: UserFormData[K]) =>
    setForm((f) => ({ ...f, [field]: value }));

  const setPrimaryRole = (role: string) => {
    setForm((f) => {
      if (role === "finance" || role === "user") {
        return { ...f, role, roles: [role], recruiter_role: "" };
      }
      const withoutExclusive = f.roles.filter(
        (value) => value !== "finance" && value !== "user",
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
      if (
        f.role === "finance" ||
        f.role === "user" ||
        role === "finance" ||
        role === "user"
      ) {
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
            <label className="block text-sm font-medium text-foreground mb-1">Rola podstawowa (primary)</label>
            <select
              value={form.role}
              onChange={(e) => setPrimaryRole(e.target.value)}
              className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
            >
              {ROLES.map((r) => (
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
                const primaryIsExclusive =
                  form.role === "finance" || form.role === "user";
                const roleIsExclusive = r === "finance" || r === "user";
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
                    {isPrimary && <span className="text-xs">(primary)</span>}
                  </label>
                );
              })}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Hybrid usery (np. DL+TAC) zaznacz obie role. Primary jest zawsze
              wybrana. Finanse i Viewer (legacy) są rolami wyłącznymi i nie
              mogą być łączone z innymi; Viewer nie jest dostępny jako rola
              dodatkowa.
            </p>
          </div>

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
