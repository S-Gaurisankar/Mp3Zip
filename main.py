import os
import sys
import uvicorn
import argparse
from pathlib import Path

def run_server(host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
    print("=" * 70)
    print("  Mp3Zip - Studio Audio Extractor & MP3 Transcoder")
    print(f"  Server starting on: http://localhost:{port}")
    print("=" * 70)
    uvicorn.run(
        "backend.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )

def main():
    parser = argparse.ArgumentParser(description="Mp3Zip Studio Music Extraction Engine")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    parser.add_argument("--cli", action="store_true", help="Launch CLI mode instead of web server")
    
    args, unknown = parser.parse_known_args()

    if args.cli:
        from cli import main as cli_main
        cli_main()
    else:
        run_server(host=args.host, port=args.port, reload=args.reload)

if __name__ == "__main__":
    main()
