import { Suspense } from "react"
import { RadaView } from "@/components/rada/RadaView"

export default function RadaPage() {
  return (
    <Suspense>
      <RadaView />
    </Suspense>
  )
}
