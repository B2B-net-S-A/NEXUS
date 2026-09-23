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
    <div className="min-h-dvh bg-background text-foreground">
      {children}
    </div>
  )
}
