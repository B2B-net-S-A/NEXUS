"use client"

import Link from "next/link"
import { ShieldOff } from "lucide-react"

import { useAuthStore, ROLE_LABELS } from "@/store/auth"

export default function ForbiddenPage() {
  const user = useAuthStore((s) => s.user)

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 bg-muted dark:bg-gray-950">
      <div className="max-w-md w-full bg-card dark:bg-card rounded-2xl shadow-xl border border-border dark:border-border p-8 text-center">
        <div className="w-14 h-14 bg-destructive/15 dark:bg-red-900/30 rounded-2xl mx-auto mb-4 flex items-center justify-center">
          <ShieldOff className="w-7 h-7 text-destructive dark:text-destructive" />
        </div>

        <h1 className="text-2xl font-bold text-foreground dark:text-foreground mb-2">
          403 — Brak uprawnień
        </h1>

        <p className="text-sm text-muted-foreground dark:text-muted-foreground mb-6">
          Ta sekcja jest zastrzeżona dla innych ról.
          {user && (
            <>
              <br />
              Jesteś zalogowany jako{" "}
              <span className="font-semibold">{ROLE_LABELS[user.role]}</span>.
            </>
          )}
        </p>

        <div className="flex flex-col sm:flex-row gap-2 justify-center">
          <Link
            href="/"
            className="px-4 py-2 bg-primary hover:bg-primary/90 text-white rounded-lg text-sm font-medium transition-colors"
          >
            Wróć na stronę główną
          </Link>
          <Link
            href="/profile"
            className="px-4 py-2 bg-muted dark:bg-muted hover:bg-muted dark:hover:bg-muted text-foreground dark:text-foreground rounded-lg text-sm font-medium transition-colors"
          >
            Mój profil
          </Link>
        </div>
      </div>
    </div>
  )
}
