"""Fetch the current ISO 4217 XML snapshot from SIX for maintainer review.

The script intentionally prints normalized rows rather than modifying source files
so currency changes remain explicit, reviewable maintenance events.
"""

from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET

URL = (
    "https://www.six-group.com/dam/download/financial-information/"
    "data-center/iso-currrency/lists/list-one.xml"
)


def main() -> int:
    """Fetch and print normalized current ISO 4217 currency/fund rows."""
    with urllib.request.urlopen(URL, timeout=30) as response:  # noqa: S310 - fixed SIX URL
        root = ET.fromstring(response.read())

    rows: dict[str, tuple[str, int, str]] = {}
    for entry in root.findall(".//CcyNtry"):
        code = entry.findtext("Ccy")
        numeric = entry.findtext("CcyNbr")
        minor = entry.findtext("CcyMnrUnts")
        name = entry.findtext("CcyNm") or code or ""

        if not code or not numeric or not minor or minor == "N.A.":
            continue
        rows[code] = (numeric, int(minor), name)

    print(
        f"Fetched {len(rows)} ISO currency/fund codes from SIX. "
        "Integrate into src/pytender/iso4217.py after review."
    )
    for code, row in sorted(rows.items()):
        print(code, row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
