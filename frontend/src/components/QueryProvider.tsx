"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactNode, useState } from "react";

export function QueryProvider({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
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
      })
  );

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
