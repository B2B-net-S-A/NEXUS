import { Login4 } from "@/components/login4"

// Inline NEXUS mark so the shadcnblocks block renders with our branding (no asset needed).
const NEXUS_LOGO =
  "data:image/svg+xml," +
  encodeURIComponent(
    "<svg xmlns='http://www.w3.org/2000/svg' width='40' height='40' viewBox='0 0 40 40'><rect width='40' height='40' rx='9' fill='#4f46e5'/><text x='20' y='27' font-family='Inter, system-ui, sans-serif' font-size='22' font-weight='700' fill='white' text-anchor='middle'>N</text></svg>",
  )

// Real shadcnblocks block (`src/components/login4.tsx`, pulled via the @shadcnblocks
// registry) — only the copy + logo are NEXUS-branded.
export default function LoginPreview() {
  return (
    <Login4
      heading="Zaloguj się do NEXUS"
      logo={{ url: "#", src: NEXUS_LOGO, alt: "NEXUS", title: "NEXUS" }}
      buttonText="Zaloguj się"
      googleText="Kontynuuj z Google"
      githubText="Kontynuuj z GitHub"
      facebookText="Kontynuuj z Microsoft"
      signupText="Nie masz konta?"
      signupUrl="#"
    />
  )
}
