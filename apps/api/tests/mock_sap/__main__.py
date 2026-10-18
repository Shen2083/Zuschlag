"""Run the mock SAP:  python -m tests.mock_sap serve | push   (from apps/api)."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import httpx

from tests.mock_sap.push import push_master_data
from tests.mock_sap.server import MockSap, MockSapConfig, create_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m tests.mock_sap")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="receive ORDERS05 at /sap/bc/idoc_xml")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8090)
    push = sub.add_parser("push", help="send MATMAS/DEBMAS to Zuschlag")
    push.add_argument("--zuschlag", default="http://localhost:8000")
    push.add_argument("--tenant", required=True)
    for p in (serve, push):
        p.add_argument("files", nargs="*", type=Path, help="IDoc files (default: provided samples)")
    args = parser.parse_args()
    config = MockSapConfig(master_data=tuple(args.files)) if args.files else MockSapConfig()

    if args.command == "serve":
        import uvicorn

        uvicorn.run(create_app(MockSap(config)), host=args.host, port=args.port)
        return

    async def run() -> None:
        async with httpx.AsyncClient(base_url=args.zuschlag, timeout=60) as client:
            results = await push_master_data(client, config.master_data, tenant_id=args.tenant)
        for r in results:
            print(json.dumps({k: r[k] for k in ("file", "idoc_type", "created", "updated")}))

    asyncio.run(run())


if __name__ == "__main__":
    main()
