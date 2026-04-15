import Link from "next/link";
import { Zap, Home, AlertTriangle } from "lucide-react";

export default function NotFound() {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 flex flex-col items-center justify-center px-4 text-center">
      {/* Logo */}
      <div className="flex items-center gap-2 mb-10">
        <Zap className="w-7 h-7 text-blue-500" aria-hidden="true" />
        <div>
          <span className="font-bold text-xl text-gray-900 dark:text-gray-100">Nexus</span>
          <span className="text-xs text-gray-400 dark:text-gray-500 ml-1">Nexus</span>
        </div>
      </div>

      {/* 404 illustration */}
      <div className="relative mb-8">
        <div
          className="text-[9rem] font-black text-gray-100 dark:text-gray-800 leading-none select-none"
          aria-hidden="true"
        >
          404
        </div>
        <div className="absolute inset-0 flex items-center justify-center">
          <AlertTriangle className="w-16 h-16 text-blue-500" aria-hidden="true" />
        </div>
      </div>

      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-2">
        Strona nie znaleziona
      </h1>
      <p className="text-sm text-gray-500 dark:text-gray-400 max-w-sm mb-8">
        Strona, której szukasz, nie istnieje lub została przeniesiona.
        Sprawdź adres URL lub wróć do dashboardu.
      </p>

      <Link
        href="/"
        className="inline-flex items-center gap-2 h-10 px-6 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2"
        aria-label="Wróć do dashboardu"
      >
        <Home className="w-4 h-4" aria-hidden="true" />
        Wróć do dashboardu
      </Link>
    </div>
  );
}
