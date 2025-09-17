from __future__ import annotations

import argparse
from typing import List


def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Kaliscan Downloader entrypoint")
    parser.add_argument("--cli", action="store_true", help="Launch the CLI instead of the GUI")
    args, remaining = parser.parse_known_args(argv)

    if args.cli:
        from cli import app

        app(args=remaining)
        return

    try:
        from gui import launch
    except ImportError as exc:  # pragma: no cover - GUI not yet implemented
        raise SystemExit("GUI dependencies are missing. Run with --cli.") from exc

    launch()


if __name__ == "__main__":  # pragma: no cover
    main()
