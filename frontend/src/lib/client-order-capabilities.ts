interface ClientOrderCapabilities {
  cyfrowy_polsat_order_types_enabled?: boolean | null;
  lotte_wedel_order_types_enabled?: boolean | null;
}

/** Jawna bramka dwóch klientów z wyborem standardowe / kosztowe / MD. */
export function hasMixedOrderTypes(
  client: ClientOrderCapabilities | null | undefined,
): boolean {
  return Boolean(
    client?.cyfrowy_polsat_order_types_enabled ||
      client?.lotte_wedel_order_types_enabled,
  );
}
