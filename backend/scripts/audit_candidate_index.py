"""Audit: python -m scripts.audit_candidate_index --output /secure/audit.json

After reviewing the exact IDs/counts/fingerprint, enqueue the approved repair:
python -m scripts.audit_candidate_index --apply /secure/audit.json --fingerprint SHA256
This queues upserts in the established durable outbox. It never deletes points.
"""

import argparse
import asyncio
import json
import os

from app.core.database import AsyncSessionLocal
from app.services.candidate_index_audit import audit_candidates, enqueue_approved_repair


async def run(args):
    async with AsyncSessionLocal() as db:
        if args.apply:
            if not args.fingerprint:
                raise ValueError("--apply requires the reviewed --fingerprint")
            with open(args.apply) as source:
                manifest = json.load(source)
            result = await enqueue_approved_repair(db, manifest, args.fingerprint)
            await db.commit()
            print(json.dumps(result))
        else:
            manifest = await audit_candidates(db)
            # IDs/hashes only, but still keep the operational manifest private.
            descriptor = os.open(
                args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            with os.fdopen(descriptor, "w") as output:
                json.dump(manifest, output, ensure_ascii=False, indent=2)
            print(
                json.dumps(
                    {
                        key: manifest[key]
                        for key in (
                            "fingerprint",
                            "database_unchanged",
                            "population",
                            "index_points",
                            "counts",
                        )
                    }
                )
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output")
    mode.add_argument("--apply")
    parser.add_argument("--fingerprint")
    asyncio.run(run(parser.parse_args()))
