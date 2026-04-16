"use client"

import Link from "next/link"
import { ShieldOff } from "lucide-react"

import { useAuthStore, ROLE_LABELS } from "@/store/auth"

export default function ForbiddenPage() {
  const user = useAuthStore((s) => s.user)

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 bg-gray-50 dark:bg-gray-950">
      <div className="max-w-md w-full bg-white dark:bg-gray-900 rounded-2xl shadow-xl border border-gray-200 dark:border-gray-700 p-8 text-center">
        <div className="w-14 h-14 bg-red-100 dark:bg-red-900/30 rounded-2xl mx-auto mb-4 flex items-center justify-center">
          <ShieldOff className="w-7 h-7 text-red-600 dark:text-red-400" />
        </div>

        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-2">
          403 — Brak uprawnień
        </h1>

        <p className="text-sm text-gray-600 dark:text-gray-400 mb-6">
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
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors"
          >
            Wróć na stronę główną
          </Link>
          <Link
            href="/profile"
            className="px-4 py-2 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-900 dark:text-gray-100 rounded-lg text-sm font-medium transition-colors"
          >
            Mój profil
          </Link>
        </div>
      </div>
    </div>
  )
}
