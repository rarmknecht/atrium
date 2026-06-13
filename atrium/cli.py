import argparse
import logging

from atrium.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="atrium", description="Atrium platform")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the Atrium server (API + trigger engine)")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true", help="Dev auto-reload")

    sub.add_parser("mcp", help="Expose the context vault to MCP clients over stdio")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )

    if args.command == "serve":
        import uvicorn

        settings = get_settings()
        uvicorn.run(
            "atrium.api.app:create_app",
            factory=True,
            host=args.host or settings.host,
            port=args.port or settings.port,
            reload=args.reload,
        )
    elif args.command == "mcp":
        from atrium.mcp_server import main as mcp_main

        mcp_main()


if __name__ == "__main__":
    main()
