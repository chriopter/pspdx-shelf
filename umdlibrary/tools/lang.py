"""What languages a disc speaks: lowercase ISO 639-1 codes with an optional
region tag (en, de, ja, pt-br), as the languages field of PSPDX writes them.

The PARAM.SFO rarely says. Where it does, it is read: localized TITLE_xx
keys, whose index is Sony's language table (the PS3 order, which the few
PSP discs that carry them follow), or a LANGUAGE-like key with codes or
English names. Otherwise the region of the disc id decides, by the table
below, and a per-disc override in the settings wins over everything: an EU
disc is "en" here until you say it is more."""
from __future__ import annotations

import re

# Sony's TITLE_xx / language index, as the system software counts.
SFO_TITLE_INDEX = {
    0: "ja", 1: "en", 2: "fr", 3: "es", 4: "de", 5: "it", 6: "nl", 7: "pt", 8: "ru", 9: "ko",
    10: "zh-tw", 11: "zh-cn", 12: "fi", 13: "sv", 14: "da", 15: "no", 16: "pl", 17: "pt-br",
    18: "en-gb", 19: "tr",
}

# English names a LANGUAGE-ish field might hold.
NAMES = {
    "english": "en", "german": "de", "deutsch": "de", "french": "fr", "francais": "fr",
    "spanish": "es", "espanol": "es", "italian": "it", "italiano": "it", "japanese": "ja",
    "dutch": "nl", "portuguese": "pt", "russian": "ru", "korean": "ko", "chinese": "zh",
    "polish": "pl", "swedish": "sv", "danish": "da", "norwegian": "no", "finnish": "fi",
    "turkish": "tr", "greek": "el", "czech": "cs", "hungarian": "hu",
}

# What a region's discs speak unless the disc or an override says more.
REGION_LANGUAGES = {"JP": ["ja"], "US": ["en"], "EU": ["en"], "AS": ["en"], "KR": ["ko"]}

LANGUAGE_KEYS = ("LANGUAGE", "LANGUAGES", "LANG")
CODE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8})?$")
MAX = 16


def normalize(code: str) -> str | None:
    """en, EN, en_GB, English -> en, en, en-gb, en; None for nonsense."""
    token = code.strip().lower().replace("_", "-")
    if token in NAMES:
        return NAMES[token]
    return token if CODE.match(token) else None


def parse_codes(text: str) -> list[str]:
    """Codes out of a comma, space, slash or pipe separated string, unique,
    in order, at most MAX."""
    out: list[str] = []
    for token in re.split(r"[,;|/\s]+", text):
        code = normalize(token) if token else None
        if code and code not in out:
            out.append(code)
    return out[:MAX]


def from_sfo(sfo: dict) -> list[str]:
    """The languages the PARAM.SFO itself names, or []."""
    out: list[str] = []
    for key, value in sfo.items():
        if not isinstance(value, str) or not value.strip():
            continue
        found = re.fullmatch(r"TITLE_(\d{2})", key.upper())
        if found:
            code = SFO_TITLE_INDEX.get(int(found.group(1)))
            if code and code not in out:
                out.append(code)
        elif key.upper() in LANGUAGE_KEYS:
            for code in parse_codes(value):
                if code not in out:
                    out.append(code)
    return out[:MAX]


def languages_of(sfo: dict, region: str, override: list[str] | None = None) -> list[str]:
    """Return language codes from override, SFO, or region fallback."""
    if override:
        return list(override)[:MAX]
    found = from_sfo(sfo)
    if found:
        return found
    return list(REGION_LANGUAGES.get(region, []))
