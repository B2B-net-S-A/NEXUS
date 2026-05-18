"use client"

import { RefreshCw, Target } from "lucide-react"

import { Button } from "@/components/ui/button"

import type { DlScope } from "./types"

interface DlHeaderProps {
  scope: DlScope
  onRefresh: () => void
}

export function DlHeader({ scope, onRefresh }: DlHeaderProps) {
  return (
    <div className="flex items-start justify-between flex-wrap gap-3">
      <div className="flex items-center gap-3">
        <div className="h-12 w-12 rounded-lg bg-amber-500 flex items-center justify-center shadow">
          <Target className="h-7 w-7 text-white" />
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">
            Panel Delivery Lead
          </p>
          <h1 className="font-semibold text-3xl md:text-4xl font-extrabold tracking-[-0.025em] text-foreground leading-tight">
            {scope === "me" ? "Moje wyniki" : "Wyniki zespołu"}
          </h1>
        </div>
      </div>
      <Button variant="outline" size="sm" onClick={onRefresh}>
        <RefreshCw className="h-4 w-4" />
        Odśwież
      </Button>
    </div>
  )
}
