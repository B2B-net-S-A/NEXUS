# CV-18: one captured candidate source for both variants

Candidate generation now separates source loading from rendering. The preview
loads file bytes, notes, identity and recruitment context once, then passes the
same frozen value object to both variants. Champion data is serialized inside
that snapshot and rebuilt per renderer, so mutable DTO fields cannot leak from
one variant to the other. Ordinary generation uses the same loader and renderer.
85 mode/source regressions and 19 snapshot/publication/preview/quota tests pass.
The API lifecycle keeps hosted coverage. The snapshot currently lives in worker
memory: durable enqueue-time inputs and one shared extracted fact ledger are
still open requirements. This package includes the two-unit admission fix.
