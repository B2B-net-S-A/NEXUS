import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    exclude: ["node_modules", ".next", "e2e"],
    css: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov", "html"],
      reportsDirectory: "./coverage",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.{test,spec}.{ts,tsx}",
        "src/test/**",
        "src/**/*.d.ts",
        "src/**/types/**",
      ],
      // Bramka „bez spadku" (QA-01, plan poprawy po audycie 14.09.2026).
      // Wartości = zmierzony baseline zaokrąglony W DÓŁ; `npm run test:coverage`
      // w CI kończy się błędem poniżej nich. Ratchet: gdy pokrycie wyraźnie
      // wzrośnie, podbij progi w tym samym PR; obniżenie wymaga uzasadnienia.
      // Zmierzone 15.09.2026 (pełny przebieg, gałąź planu poprawy QA):
      // linie/instrukcje 53,48%, gałęzie 78,05%, funkcje 54,97%.
      thresholds: {
        lines: 53,
        statements: 53,
        branches: 77.5,
        functions: 54,
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
