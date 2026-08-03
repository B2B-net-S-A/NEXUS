"use client"

import { useEffect } from"react"
import { useRouter } from"next/navigation"

import {
 onboardingPersona,
 requiresOnboarding,
 useAuthStore,
} from"@/store/auth"
import { OnboardingDLV2 } from"@/components/v2/forms/OnboardingDLV2"
import { OnboardingRecruiterV2 } from"@/components/v2/forms/OnboardingRecruiterV2"

function FullScreenLoader() {
 return (
 <div className="min-h-screen flex items-center justify-center bg-background">
 <p className="text-sm text-muted-foreground">Ładowanie…</p>
 </div>
 )
}

export default function OnboardingPage() {
 const router = useRouter()
 const user = useAuthStore((s) => s.user)
 const hydrated = useAuthStore((s) => s.hydrated)
 const hydrate = useAuthStore((s) => s.hydrate)

 useEffect(() => {
 if (!hydrated) hydrate()
 }, [hydrated, hydrate])

 useEffect(() => {
 if (!hydrated) return
 if (!user) {
 router.replace("/login?next=/onboarding")
 return
 }
 if (!requiresOnboarding(user)) {
 router.replace("/")
 }
 }, [hydrated, user, router])

 if (!hydrated) return <FullScreenLoader />
 if (!user || !requiresOnboarding(user)) return <FullScreenLoader />

 const persona = onboardingPersona(user)
 if (persona === "delivery_lead") return <OnboardingDLV2 />
 if (persona === "recruiter") return <OnboardingRecruiterV2 />
 return <FullScreenLoader />
}
