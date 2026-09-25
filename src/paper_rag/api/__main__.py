"""Run the server.

  python -m paper_rag.api            local mode: app on 127.0.0.1:8000, no access gate
  python -m paper_rag.api --public   public mode: gated app on :8000 (point the tunnel here) +
                                     admin console on 127.0.0.1:8001 (never tunnel this)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import secrets
import sys
import threading

import uvicorn

from paper_rag.api.admin import create_admin_app
from paper_rag.api.server import create_public_app
from paper_rag.api.state import build_state
from paper_rag.config import get_settings


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="python -m paper_rag.api", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--public", action="store_true", help="enable the access gate and the admin console")
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--admin-port", type=int, default=settings.admin_port)
    parser.add_argument("--no-warmup", action="store_true", help="don't pre-load the embedding model")
    args = parser.parse_args(argv)
    if args.port == args.admin_port:
        parser.error("--port and --admin-port must differ")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    state = build_state(settings, public=args.public)
    if not args.no_warmup:
        threading.Thread(target=state.toolbox.embedder.encode_query, args=("warmup",), daemon=True).start()

    public_app = create_public_app(state)
    servers = [uvicorn.Server(uvicorn.Config(public_app, host="127.0.0.1", port=args.port, log_level="warning",
                                             proxy_headers=False))]
    banner = [f"\n  App:    http://127.0.0.1:{args.port}   ({'public mode, access-gated' if args.public else 'local mode'})"]
    if args.public:
        assert state.access is not None
        admin_token = secrets.token_urlsafe(24)
        admin_app = create_admin_app(state.access, admin_token, settings.frontend_dist, args.port)
        servers.append(uvicorn.Server(uvicorn.Config(admin_app, host="127.0.0.1", port=args.admin_port,
                                                     log_level="warning")))
        banner += [f"  Admin:  http://127.0.0.1:{args.admin_port}/?token={admin_token}",
                   f"  Tunnel: cloudflared tunnel --url http://localhost:{args.port}   (never expose the admin port)"]
    stats = state.kg.stats()
    banner.append(f"  Corpus: {stats['papers']} papers, {stats['nodes']} graph nodes, {state.vs.count()} chunks\n")
    print("\n".join(banner), flush=True)

    async def serve_all() -> None:
        await asyncio.gather(*(s.serve() for s in servers))

    try:
        asyncio.run(serve_all())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
