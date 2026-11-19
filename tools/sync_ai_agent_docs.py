"""Sync the public AI guides bundled with the Web dashboard.

Run after editing the source guides; use --check in validation.
"""

import argparse
from pathlib import Path


GUIDES = ("AI_AGENT_INTEGRATION.md", "AI_MCP_TRADING.md", "AI_STRATEGY_MIGRATION.md", "API_REFERENCE.md")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = root / "web_dashboard" / "docs"
    stale = []
    for name in GUIDES:
        source = (root / "docs" / name).read_bytes()
        output = target / name
        if args.check:
            if not output.is_file() or output.read_bytes() != source:
                stale.append(name)
        else:
            target.mkdir(parents=True, exist_ok=True)
            output.write_bytes(source)
    if stale:
        raise SystemExit("Bundled guides out of date; run python tools/sync_ai_agent_docs.py: " + ", ".join(stale))


if __name__ == "__main__":
    main()
