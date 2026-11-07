"""One game, several discs: the same title sold as ULES (EU), ULUS (US) and
ULJS (JP), or a Platinum reissue. The library shows them as one tile with a
badge per version. The grouping key is the title, case-folded, with the
trailing region, language, version and edition markers stripped."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

REGION_ORDER = {"EU": 0, "US": 1, "JP": 2, "AS": 3, "KR": 4, "unknown": 9}

# What a bracketed tail may say and still be the same game.
_WORDS = (r"europe|eu|pal|usa|us|ntsc(?:-u|-j)?|japan|jp|asia|korea|germany|france|spain|italy|uk|"
          r"australia|en|de|fr|es|it|ja|nl|pt|ru|multi\s*\d*|en,\s*[a-z,\s]+|v\s*\d[\d.]*|rev\s*\d+|"
          r"[a-z]{4}[-_]?\d{5}|platinum|essentials|greatest hits|psp the best|the best|disc \d+|"
          r"demo|trial|special edition|collector'?s edition|limited edition")
_BRACKETED = re.compile(rf"\s*[\(\[](?:{_WORDS})[\)\]]\s*$", re.I)
_DASHED = re.compile(r"\s*[-–:]\s*(?:european|us|japanese|uk|german|french|spanish|italian|pal|ntsc)"
                     r"\s+(?:version|edition|release)\s*$", re.I)
_EDITION = re.compile(r"\s+(?:platinum|essentials|greatest hits|psp the best|the best)\s*$", re.I)
_SYMBOLS = re.compile(r"[™®©]")


def normalize_title(title: str) -> str:
    """The title with its version markers removed, case-folded, spaces
    collapsed: what two discs of one game have in common."""
    text = unicodedata.normalize("NFKC", _SYMBOLS.sub("", title or ""))
    while True:
        before = text
        text = _BRACKETED.sub("", text)
        text = _DASHED.sub("", text)
        text = _EDITION.sub("", text)
        text = text.strip(" -–:_.")
        if text == before:
            break
    text = " ".join(text.casefold().split())
    return text


def game_key(title: str) -> str:
    """Return a stable grouping key for a title."""
    return normalize_title(title) or "?"


def games(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows grouped by game_key: one dict per game, versions ordered by
    region then disc id, the first readable one with an icon on the tile."""
    by_key: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_key.setdefault(row["game_key"], []).append(row)
    out = []
    for key, versions in by_key.items():
        versions.sort(key=lambda r: (REGION_ORDER.get(r["region"], 9), r["disc_key"], -r["mtime"]))
        face = next((v for v in versions if v["has_media"].get("ICON0.PNG")), versions[0])
        languages: list[str] = []
        for v in versions:
            for code in v["languages"]:
                if code not in languages:
                    languages.append(code)
        out.append({
            "key": key,
            "title": face["title"] or face["name"],
            "face": face,
            "versions": versions,
            "languages": languages,
            "regions": sorted({v["region"] for v in versions}, key=lambda r: REGION_ORDER.get(r, 9)),
            "size": sum(v["size"] for v in versions),
            "mtime": max(v["mtime"] for v in versions),
            "errors": sum(v["status"] != "ok" for v in versions),
        })
    out.sort(key=lambda g: g["title"].casefold())
    return out
