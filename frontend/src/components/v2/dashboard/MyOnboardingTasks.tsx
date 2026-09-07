"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { allocationApi } from "@/lib/recruitment-allocation-api"
import { Button } from "@/components/ui/button"

export function MyOnboardingTasks() {
  const client = useQueryClient()
  const query = useQuery({
    queryKey: ["my-onboarding-tasks"],
    queryFn: async () => {
      const first = await allocationApi.onboarding()
      const items = [...first.items]
      let cursor = first.next_cursor
      while (cursor !== null) {
        const page = await allocationApi.onboarding(cursor)
        items.push(...page.items)
        cursor = page.next_cursor
      }
      return items
    },
    refetchInterval: 30_000,
  })
  const complete = useMutation({
    mutationFn: allocationApi.complete,
    onSuccess: () => client.invalidateQueries({ queryKey: ["my-onboarding-tasks"] }),
  })
  if (!query.data?.length && !query.isError) return null
  return (
    <section
      className="border-t border-border p-4"
      aria-label="Moje zadania onboardingowe"
    >
      <h3 className="font-medium">Zadania onboardingowe · własne i przejęte</h3>
      {(query.isError || complete.isError) && (
        <p role="alert" className="text-sm text-destructive">
          Nie udało się odczytać lub zapisać zadań.{" "}
          <button onClick={() => query.refetch()}>Ponów odczyt</button>
        </p>
      )}
      <ul className="mt-2 divide-y divide-border">
        {query.data?.map((task) => (
          <li
            key={task.id}
            className="flex items-center justify-between gap-3 py-2 text-sm"
          >
            <div>
              {task.label}
              <p className="text-xs text-muted-foreground">
                Termin: {task.due_date ?? "Nie ustalono"}
                {task.substitution && ` · W zastępstwie do ${task.substitution.end_date}`}
              </p>
            </div>
            <Button
              size="sm"
              variant="outline"
              disabled={complete.isPending}
              onClick={() => complete.mutate(task.id)}
            >
              Wykonane
            </Button>
          </li>
        ))}
      </ul>
    </section>
  )
}
