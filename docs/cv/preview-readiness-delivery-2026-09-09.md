# CV-18: trial admission uses the exact recipe snapshot

Preview readiness previously used published client settings while its worker
used the saved draft. It now validates both variants before quota: the frozen
draft (including content ceiling and required inputs) and the explicit unruled
baseline. Internal readiness overrides are client-scoped and preserve normal
published behavior for all other callers. Missing inputs identify the failing
variant. Twenty-six focused tests cover mode/cap resolution and both rejection
paths; hosted API coverage is retained. This does not yet freeze candidate
sources or reuse one extracted fact ledger across variants.
