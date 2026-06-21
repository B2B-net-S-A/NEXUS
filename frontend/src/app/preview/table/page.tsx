import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"

// Struktura 1:1 z Tailwind Plus „Application UI → Lists → Tables (Simple)" —
// te same triki layoutu (flow-root, -mx/-my, sm:pl-0, nagłówek + akcja, kolumna Edit).
// Zaadaptowane: zaszyte text-gray-*/divide-gray-*/bg-indigo-600 → tokeny NEXUSa.

type StageVariant = "soft" | "info" | "warning" | "success" | "neutral"

const CANDIDATES: {
  name: string
  role: string
  email: string
  stage: string
  variant: StageVariant
}[] = [
  { name: "Jan Kowalski", role: "Senior React Developer", email: "jan.kowalski@example.com", stage: "Interview", variant: "info" },
  { name: "Anna Nowak", role: "DevOps Engineer", email: "anna.nowak@example.com", stage: "Rekomendacja", variant: "soft" },
  { name: "Piotr Wiśniewski", role: "Data Engineer", email: "p.wisniewski@example.com", stage: "Oferta", variant: "warning" },
  { name: "Magdalena Lewandowska", role: "QA Automation", email: "m.lewandowska@example.com", stage: "Weryfikacja", variant: "neutral" },
  { name: "Tomasz Kamiński", role: "Backend (Go)", email: "t.kaminski@example.com", stage: "Placement", variant: "success" },
  { name: "Katarzyna Zielińska", role: "Product Designer", email: "k.zielinska@example.com", stage: "Nowy", variant: "neutral" },
]

function Initials({ name }: { name: string }) {
  const i = name
    .split(" ")
    .map((s) => s[0])
    .slice(0, 2)
    .join("")
    .toUpperCase()
  return (
    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[11px] font-semibold text-primary">
      {i}
    </span>
  )
}

export default function TablePreview() {
  return (
    <div className="mx-auto max-w-[1080px] px-4 py-10 sm:px-6 lg:px-8">
      <div className="sm:flex sm:items-center">
        <div className="sm:flex-auto">
          <h1 className="text-base font-semibold text-foreground">Kandydaci w procesie</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Kandydaci aktywni w Twoich rekrutacjach — imię, stanowisko, e-mail i etap.
          </p>
        </div>
        <div className="mt-4 sm:ml-16 sm:mt-0 sm:flex-none">
          <button
            type="button"
            className="block rounded-md bg-primary px-3 py-2 text-center text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"
          >
            Dodaj kandydata
          </button>
        </div>
      </div>
      <div className="mt-8 flow-root">
        <div className="-mx-4 -my-2 overflow-x-auto sm:-mx-6 lg:-mx-8">
          <div className="inline-block min-w-full py-2 align-middle sm:px-6 lg:px-8">
            <table className="min-w-full divide-y divide-border">
              <thead>
                <tr>
                  <th className="py-3.5 pl-4 pr-3 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground sm:pl-0">
                    Kandydat
                  </th>
                  <th className="px-3 py-3.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Stanowisko
                  </th>
                  <th className="px-3 py-3.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    E-mail
                  </th>
                  <th className="px-3 py-3.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Etap
                  </th>
                  <th className="py-3.5 pl-3 pr-4 sm:pr-0">
                    <span className="sr-only">Akcje</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {CANDIDATES.map((c) => (
                  <tr key={c.email} className="transition-colors hover:bg-muted/40">
                    <td className="whitespace-nowrap py-4 pl-4 pr-3 text-sm sm:pl-0">
                      <div className="flex items-center gap-3">
                        <Initials name={c.name} />
                        <span className="font-medium text-foreground">{c.name}</span>
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-3 py-4 text-sm text-muted-foreground">
                      {c.role}
                    </td>
                    <td className="whitespace-nowrap px-3 py-4 text-sm text-muted-foreground">
                      {c.email}
                    </td>
                    <td className="whitespace-nowrap px-3 py-4 text-sm">
                      <Badge variant={c.variant} size="sm">
                        {c.stage}
                      </Badge>
                    </td>
                    <td className="whitespace-nowrap py-4 pl-3 pr-4 text-right text-sm font-medium sm:pr-0">
                      <a href="#" className={cn("text-primary transition-colors hover:text-primary/80")}>
                        Edytuj<span className="sr-only">, {c.name}</span>
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
