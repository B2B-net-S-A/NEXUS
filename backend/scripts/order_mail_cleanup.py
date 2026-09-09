"""Run the explicitly requested one-off; audit is the default (no writes)."""

import argparse
import asyncio
import base64
import gzip
import json

from app.core.database import AsyncSessionLocal
from app.services.order_mail_cleanup import build_cleanup_plan, apply_cleanup_plan


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fingerprint")
    args = parser.parse_args()
    async with AsyncSessionLocal() as db:
        if args.fingerprint:
            result = await apply_cleanup_plan(db, args.fingerprint)
            await db.commit()
        else:
            result = await build_cleanup_plan(db)
            await db.rollback()
    print("===ORDER-MAIL-CLEANUP-PAYLOAD===")
    print(
        base64.b64encode(
            gzip.compress(json.dumps(result, ensure_ascii=False, default=str).encode())
        ).decode()
    )
    print("===ORDER-MAIL-CLEANUP-END===")


if __name__ == "__main__":
    asyncio.run(main())
