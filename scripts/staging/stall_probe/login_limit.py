"""40 nieudanych logowań z jednego IP, każde na nowym połączeniu: ile przeszło przez limit."""

import collections
import sys

import httpx

base = sys.argv[1]
label = sys.argv[2]
counts = collections.Counter()
for i in range(40):
    with httpx.Client(timeout=10) as c:  # nowe połączenie = kernel wybiera proces
        r = c.post(
            base + "/api/auth/login",
            json={"email": f"nikt{i}@example.com", "password": "zle-haslo"},
        )
        counts[r.status_code] += 1
print(
    label,
    dict(sorted(counts.items())),
    "przepuszczone przez limit:",
    sum(v for k, v in counts.items() if k != 429),
)
