"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { AdminUser } from "./types";

type ResetMode = "manual" | "send_link";

interface ResetPasswordModalProps {
  user: AdminUser;
  onClose: () => void;
  onSaveManual: (password: string) => void;
  onSendLink: () => void;
  loading: boolean;
}

export function ResetPasswordModal({
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

export default ResetPasswordModal;
