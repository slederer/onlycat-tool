"""Find websites using live streaming technology vendors via BuiltWith API."""

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

load_dotenv()

# Map friendly names to BuiltWith technology identifiers
STREAMING_VENDORS = {
    "Mux": "Mux",
    "Agora": "Agora",
    "AWS IVS": "Amazon Interactive Video Service",
    "Cloudflare Stream": "Cloudflare Stream",
    "Vonage Video": "Vonage Video API",
    "Vimeo OTT": "Vimeo OTT",
    "Vimeo": "Vimeo",
    "Wistia": "Wistia",
    "JW Player": "JW Player",
    "Brightcove": "Brightcove",
    "Vidyard": "Vidyard",
    "Kaltura": "Kaltura",
    "Livestream": "Livestream",
    "Dacast": "DaCast",
    "IBM Video": "IBM Video Streaming",
    "Panopto": "Panopto",
}

def _fmt_ts(ts) -> str:
    """Convert a Unix timestamp to YYYY-MM-DD."""
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OSError):
        return str(ts)


LISTS_API_URL = "https://api.builtwith.com/lists8/api.json"
DOMAIN_API_URL = "https://api.builtwith.com/v21/api.json"


def search_by_technology(
    client: httpx.Client, api_key: str, tech_name: str, limit: int
) -> list[dict]:
    """Search BuiltWith for sites using a specific technology."""
    results = []
    offset = ""

    while True:
        params = {"KEY": api_key, "TECH": tech_name}
        if offset:
            params["OFFSET"] = offset

        resp = client.get(LISTS_API_URL, params=params, timeout=30)

        if resp.status_code == 403:
            raise PermissionError(
                f"API returned 403 — your BuiltWith plan may not include Lists API access."
            )
        if resp.status_code == 401:
            raise PermissionError("Invalid API key.")
        resp.raise_for_status()

        data = resp.json()

        if errors := data.get("Errors"):
            raise RuntimeError(f"API errors: {errors}")

        for site in data.get("Results", []):
            results.append(
                {
                    "domain": site.get("D", ""),
                    "rank": site.get("FL", ""),
                    "first_detected": _fmt_ts(site.get("FD")),
                    "last_detected": _fmt_ts(site.get("LD")),
                }
            )
            if len(results) >= limit:
                return results

        next_offset = data.get("NextOffset", "")
        if not next_offset or not data.get("Results"):
            break
        offset = next_offset

    return results


def lookup_domain(
    client: httpx.Client, api_key: str, domain: str
) -> dict | None:
    """Look up a single domain's streaming tech stack."""
    resp = client.get(
        DOMAIN_API_URL,
        params={"KEY": api_key, "LOOKUP": domain},
        timeout=30,
    )
    if resp.status_code != 200:
        return None
    return resp.json()


def find_streaming_tech_for_domain(
    client: httpx.Client, api_key: str, domain: str
) -> list[str]:
    """Check which streaming vendors a specific domain uses."""
    data = lookup_domain(client, api_key, domain)
    if not data:
        return []

    found = []
    all_tech_names = set()

    for result in data.get("Results", []):
        for path in result.get("Result", {}).get("Paths", []):
            for tech in path.get("Technologies", []):
                all_tech_names.add(tech.get("Name", ""))

    builtwith_names = set(STREAMING_VENDORS.values())
    for name in all_tech_names:
        if name in builtwith_names:
            found.append(name)

    return found


def print_table(rows: list[dict], vendor_col: bool = True) -> None:
    """Print results as a formatted table."""
    if not rows:
        print("  No results found.")
        return

    if vendor_col:
        header = f"  {'Vendor':<20} {'Domain':<40} {'Rank':<12} {'Last Detected':<15}"
        print(header)
        print("  " + "-" * (len(header) - 2))
        for r in rows:
            print(
                f"  {r.get('vendor', ''):<20} {r['domain']:<40} "
                f"{str(r.get('rank', '')):<12} {r.get('last_detected', ''):<15}"
            )
    else:
        header = f"  {'Domain':<40} {'Rank':<12} {'Last Detected':<15}"
        print(header)
        print("  " + "-" * (len(header) - 2))
        for r in rows:
            print(
                f"  {r['domain']:<40} "
                f"{str(r.get('rank', '')):<12} {r.get('last_detected', ''):<15}"
            )


def write_csv(rows: list[dict], path: str) -> None:
    """Write results to a CSV file."""
    if not rows:
        return
    fieldnames = ["vendor", "domain", "rank", "first_detected", "last_detected"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nResults written to {path}")


def cmd_search(args: argparse.Namespace) -> None:
    """Search for sites using streaming vendors."""
    api_key = os.getenv("BUILTWITH_API_KEY")
    if not api_key:
        print("Error: BUILTWITH_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    if args.vendors:
        vendor_names = [v.strip() for v in args.vendors.split(",")]
        vendors = {}
        for name in vendor_names:
            matched = False
            for key, val in STREAMING_VENDORS.items():
                if key.lower() == name.lower():
                    vendors[key] = val
                    matched = True
                    break
            if not matched:
                print(f"Warning: Unknown vendor '{name}'. Skipping.")
                print(f"  Available: {', '.join(STREAMING_VENDORS.keys())}")
        if not vendors:
            sys.exit(1)
    else:
        vendors = STREAMING_VENDORS

    all_results = []
    client = httpx.Client()

    try:
        for i, (friendly_name, tech_name) in enumerate(vendors.items()):
            if i > 0:
                time.sleep(1)  # rate limit courtesy

            print(f"\nSearching for sites using {friendly_name} ({tech_name})...")

            try:
                results = search_by_technology(
                    client, api_key, tech_name, args.limit
                )
                for r in results:
                    r["vendor"] = friendly_name

                print(f"  Found {len(results)} site(s)")
                if results and args.verbose:
                    print_table(results, vendor_col=False)

                all_results.extend(results)

            except PermissionError as e:
                print(f"  Error: {e}", file=sys.stderr)
                if "403" in str(e):
                    print(
                        "  The Lists API may require a paid BuiltWith plan.",
                        file=sys.stderr,
                    )
                break
            except Exception as e:
                print(f"  Error searching {friendly_name}: {e}", file=sys.stderr)
                continue
    finally:
        client.close()

    print(f"\n{'='*70}")
    print(f"Total: {len(all_results)} sites across {len(vendors)} vendor(s)\n")
    print_table(all_results)

    if args.output:
        write_csv(all_results, args.output)


def cmd_lookup(args: argparse.Namespace) -> None:
    """Look up streaming tech for a specific domain."""
    api_key = os.getenv("BUILTWITH_API_KEY")
    if not api_key:
        print("Error: BUILTWITH_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    client = httpx.Client()
    try:
        print(f"Looking up streaming tech for {args.domain}...")
        found = find_streaming_tech_for_domain(client, api_key, args.domain)
        if found:
            print(f"  Streaming vendors detected: {', '.join(found)}")
        else:
            print("  No known streaming vendors detected.")

        if args.verbose:
            data = lookup_domain(client, api_key, args.domain)
            if data:
                import json
                print(json.dumps(data, indent=2))
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find websites using live streaming technology vendors (via BuiltWith)"
    )
    subparsers = parser.add_subparsers(dest="command")

    # Search command (default)
    search_parser = subparsers.add_parser(
        "search", help="Search for sites using streaming vendors"
    )
    search_parser.add_argument(
        "--vendors", "-v",
        help=f"Comma-separated vendor names (default: all). Options: {', '.join(STREAMING_VENDORS.keys())}",
    )
    search_parser.add_argument(
        "--output", "-o",
        help="Path to write CSV output",
    )
    search_parser.add_argument(
        "--limit", "-n",
        type=int,
        default=50,
        help="Max results per vendor (default: 50)",
    )
    search_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed results per vendor",
    )

    # Lookup command
    lookup_parser = subparsers.add_parser(
        "lookup", help="Check which streaming vendors a specific domain uses"
    )
    lookup_parser.add_argument("domain", help="Domain to look up (e.g. twitch.tv)")
    lookup_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show full API response",
    )

    # List vendors command
    subparsers.add_parser("vendors", help="List all tracked streaming vendors")

    args = parser.parse_args()

    if args.command == "lookup":
        cmd_lookup(args)
    elif args.command == "vendors":
        print("Tracked streaming vendors:")
        for name, tech in STREAMING_VENDORS.items():
            print(f"  {name:<20} -> BuiltWith: {tech}")
    elif args.command == "search" or args.command is None:
        # Default to search
        if args.command is None:
            args = parser.parse_args(["search"])
        cmd_search(args)


if __name__ == "__main__":
    main()
