import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Onboarding · Nexus",
}

export default function OnboardingLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div
      data-ui="v2"
      className="min-h-screen bg-[hsl(var(--bg-canvas))] text-[hsl(var(--text-body))]"
    >
      {children}
    </div>
  )
}
