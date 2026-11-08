/**
 * Polskie nazwy kategorii słownika umiejętności (`skills.category`).
 * Klucze zostają po angielsku w bazie; role (`role_*`) to jedna etykieta.
 */

const LABELS: Record<string, string> = {
  language: "Języki programowania",
  backend: "Backend",
  frontend: "Frontend",
  mobile: "Mobile",
  database: "Bazy danych",
  data: "Dane i analityka",
  cloud: "Chmura",
  devops: "DevOps",
  qa: "Testowanie",
  security: "Bezpieczeństwo",
  ai: "AI",
  tools: "Narzędzia",
  standards: "Standardy",
  methodology: "Metodyki",
  messaging: "Kolejki i komunikacja",
  practice: "Praktyki",
  domain: "Wiedza domenowa",
};

export function skillCategoryLabel(category: string | null | undefined): string {
  if (!category) return "—";
  if (category.startsWith("role_")) return "Rola";
  return LABELS[category] ?? category;
}
