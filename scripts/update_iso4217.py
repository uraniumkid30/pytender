"""Regenerate ISO metadata from SIX List One XML.

This script intentionally requires network access and is not part of runtime imports.
Review the resulting diff and current SIX amendments before committing it.
"""

from __future__ import annotations
import urllib.request, xml.etree.ElementTree as ET


URL="https://www.six-group.com/dam/download/financial-information/data-center/iso-currrency/lists/list-one.xml"


def main()->int:
    with urllib.request.urlopen(URL,timeout=30) as r: root=ET.fromstring(r.read())
    rows={}
    for entry in root.findall(".//CcyNtry"):
        code=entry.findtext("Ccy"); numeric=entry.findtext("CcyNbr"); minor=entry.findtext("CcyMnrUnts"); name=entry.findtext("CcyNm") or code or ""
        if not code or not numeric or not minor or minor=="N.A.": continue
        rows[code]=(numeric,int(minor),name)
    print(f"Fetched {len(rows)} ISO currency/fund codes from SIX. Integrate into src/pytender/iso4217.py after review.")
    for code,row in sorted(rows.items()):
        print(code,row)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
