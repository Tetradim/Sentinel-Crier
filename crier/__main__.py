import argparse
import os
from .config import Config


def main():
    parser = argparse.ArgumentParser(description="Sentinel Crier — broker fill alerts")
    parser.add_argument("command", choices=["serve", "watch", "export-history", "enroll"], nargs="?", default="serve")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--output", default="data/webull-history.json")
    parser.add_argument("--baseline", help="Path to a complete verified baseline JSON manifest")
    args = parser.parse_args()
    config = Config.from_env()
    if args.command == "serve":
        import uvicorn
        from .app import create_app
        print(f"Crier: http://{args.host}:{args.port}")
        print("Access token: CRIER_ACCESS_TOKEN environment variable or data/access-token. Keep it private.")
        uvicorn.run(create_app(config), host=args.host, port=args.port, access_log=False)
    elif args.command == "watch":
        from .webull import observe
        observe(config)
    elif args.command == "enroll":
        if not args.baseline: parser.error("enroll requires --baseline")
        import json
        from .store import Store
        from .webull import enroll
        with open(args.baseline, encoding="utf-8") as f: manifest = json.load(f)
        enroll(Store(config.data_dir / "crier.sqlite3"), manifest)
        print("Baseline stored. Restart the observer to use this enrollment.")
    else:
        from .webull import export_history
        export_history(args.output)
        print("Private history export saved. This command does not post alerts.")


if __name__ == "__main__": main()
