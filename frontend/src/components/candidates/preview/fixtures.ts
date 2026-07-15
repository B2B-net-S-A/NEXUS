export interface CandidatePreviewFixture {
  id: number
  name: string
  initials: string
  title: string
  location: string
  email: string
  phone: string
  status: "Aktywny" | "W procesie" | "Nieaktywny"
  availability: string
  rate: string
  recruitment: string
  stage: string
  lastActivity: string
  score?: number
  skills: string[]
  summary: string
  cvName?: string
}

export const CANDIDATE_PREVIEW_FIXTURES: CandidatePreviewFixture[] = [
  {
    id: 101,
    name: "Janusz Prażmowski",
    initials: "JP",
    title: "Senior DevOps / Cloud Engineer",
    location: "Warszawa · hybrydowo",
    email: "janusz.prazmowski@example.com",
    phone: "+48 515 010 530",
    status: "Aktywny",
    availability: "Od 1 sierpnia",
    rate: "190–220 PLN/h",
    recruitment: "Cloud Architect",
    stage: "Screening techniczny",
    lastActivity: "Notatka · dzisiaj, 09:42",
    score: 82,
    skills: ["AWS", "Azure", "Kubernetes", "Terraform", "Docker", "CI/CD"],
    summary:
      "Ponad 8 lat doświadczenia w projektowaniu i utrzymaniu platform chmurowych. Prowadził migracje do Kubernetes oraz automatyzację infrastruktury dla środowisk o wysokiej dostępności.",
    cvName: "JanuszPrazmowskiResume.pdf",
  },
  {
    id: 102,
    name: "Aleksandra Kowalska",
    initials: "AK",
    title: "Senior Java Developer",
    location: "Kraków · zdalnie",
    email: "aleksandra.kowalska@example.com",
    phone: "+48 600 200 100",
    status: "W procesie",
    availability: "2 tygodnie",
    rate: "170–190 PLN/h",
    recruitment: "Backend Engineer",
    stage: "Rekomendacja",
    lastActivity: "E-mail · wczoraj, 15:10",
    score: 71,
    skills: ["Java", "Spring", "Kafka", "PostgreSQL"],
    summary: "Backend engineer specjalizująca się w systemach transakcyjnych.",
    cvName: "Aleksandra_Kowalska_CV.pdf",
  },
  {
    id: 103,
    name: "Michał Nowicki",
    initials: "MN",
    title: "Business Analyst",
    location: "Wrocław",
    email: "michal.nowicki@example.com",
    phone: "+48 501 321 789",
    status: "Nieaktywny",
    availability: "Do ustalenia",
    rate: "140 PLN/h",
    recruitment: "—",
    stage: "Brak aktywnego procesu",
    lastActivity: "Telefon · 12 lipca",
    score: 44,
    skills: ["BPMN", "UML", "SQL"],
    summary: "Analityk biznesowo-systemowy z doświadczeniem w bankowości.",
  },
]

export const CANDIDATE_PREVIEW_RECOMMENDATIONS = [
  {
    id: 201,
    title: "Cloud Architect",
    location: "Warszawa",
    rate: "22 000–32 000 PLN",
    score: 82,
    strength: "Bardzo dobre pokrycie AWS, Kubernetes i Terraform.",
    gap: "Brak potwierdzonego doświadczenia z FinOps.",
  },
  {
    id: 202,
    title: "DevOps / Cloud Engineer",
    location: "Warszawa / zdalnie",
    rate: "18 000–28 000 PLN",
    score: 70,
    strength: "Doświadczenie z CI/CD oraz środowiskami wielochmurowymi.",
    gap: "Warto zweryfikować poziom Google Cloud.",
  },
] as const

export const CANDIDATE_PREVIEW_ACTIVITIES = [
  { id: 1, title: "Dodano notatkę po rozmowie", meta: "Dzisiaj, 09:42 · Anna Kowalska" },
  { id: 2, title: "Przeniesiono do etapu Screening techniczny", meta: "Wczoraj, 15:10" },
  { id: 3, title: "Otwarto przesłane CV", meta: "11 lipca, 12:03" },
] as const
