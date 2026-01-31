import argparse
import sys

from .migrator import apply_schema


def main() -> int:
    parser = argparse.ArgumentParser(description="ClickHouse schema migrator")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("apply", help="Apply metadata-driven schema updates")

    args = parser.parse_args()
    if args.command == "apply":
        apply_schema()
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
