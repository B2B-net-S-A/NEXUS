"use client";

import * as Sentry from "@sentry/nextjs";
import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { ReactNode, useState } from "react";

import { createQueryFailureReporter } from "@/lib/query-error-telemetry";

export function QueryProvider({ children }: { children: ReactNode }) {
  const [queryClient] = useState(() => {
    // Błędy obsłużone przez react-query nie docierają do Sentry same — bez tego
    // 503 z proxy, timeouty i 5xx widoczne na ekranach nie zostawiały śladu
    // (reaudyt 14.09.2026, R07). Szczegóły w `lib/query-error-telemetry.ts`.
    const reportFailure = createQueryFailureReporter({
      capture: (error, context) => {
        Sentry.captureException(error, context);
      },
    });
    return new QueryClient({
      queryCache: new QueryCache({ onError: (error) => reportFailure(error) }),
      mutationCache: new MutationCache({
        onError: (error, _variables, _context, mutation) => reportFailure(error, mutation),
      }),
      defaultOptions: {
        queries: {
          staleTime: 30_000,
          // Zero: ponawianie chwilowych awarii (502/503/504, brak odpowiedzi)
          // robi interceptor axios w `lib/api.ts` — do 2 powtórek z backoffem
          // i jitterem. Druga warstwa tutaj mnożyła to do 6 fizycznych żądań
          // na jeden odczyt, a 4xx/500 i tak nie warto ponawiać.
          retry: 0,
        },
      },
    });
  });

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
