const TIME_ZONE = "Europe/Warsaw"

export interface LoginGreeting {
  greeting: string
  date: string
}

/** Powitanie na ekranie logowania: pora dnia i data liczone w czasie firmy, nie przeglądarki. */
export function loginGreeting(now: Date): LoginGreeting {
  const hour = Number(
    new Intl.DateTimeFormat("pl-PL", { hour: "numeric", hourCycle: "h23", timeZone: TIME_ZONE }).format(now),
  )
  const date = new Intl.DateTimeFormat("pl-PL", {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: TIME_ZONE,
  }).format(now)
  return {
    greeting: hour >= 5 && hour < 18 ? "Dzień dobry" : "Dobry wieczór",
    date: date.charAt(0).toUpperCase() + date.slice(1),
  }
}
