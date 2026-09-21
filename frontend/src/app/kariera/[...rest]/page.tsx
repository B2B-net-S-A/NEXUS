import { notFound } from "next/navigation";

/**
 * Łapacz dla nieznanych adresów pod `/kariera/*`. Middleware kieruje tu każdy
 * adres spoza listy na hoście kariery — `notFound()` daje status 404 i
 * terminalowe `not-found.tsx` w motywie kariery zamiast 404 aplikacji.
 */
export default function CareerCatchAll(): never {
  notFound();
}
