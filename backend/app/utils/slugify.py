from __future__ import annotations

import re

from pykakasi import kakasi

_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("区", "-ku"),
    ("市", "-shi"),
    ("町", "-cho"),
    ("村", "-mura"),
)

_kakasi = kakasi()
_kakasi.setMode("H", "a")
_kakasi.setMode("K", "a")
_kakasi.setMode("J", "a")
_converter = _kakasi.getConverter()


def _romanize(text: str) -> str:
    roman = _converter.do(text).lower()
    return re.sub(r"[^a-z0-9]+", "-", roman).strip("-")


def municipality_slug(name_ja: str, fallback_code: str = "") -> str:
    base = name_ja
    suffix = ""
    for ja, en in _SUFFIXES:
        if name_ja.endswith(ja):
            base = name_ja[: -len(ja)]
            suffix = en
            break

    roman = _romanize(base)
    if suffix:
        slug = f"{roman}{suffix}" if roman else suffix.lstrip("-")
    else:
        slug = roman
    return slug or fallback_code


def dedupe_slug(slug: str, code: str) -> str:
    if not slug:
        return code
    return slug


_DISTRICT_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("丁目", "-chome"),
    ("町", "-cho"),
    ("台", "-dai"),
)


def district_slug(name: str, fallback_code: str = "") -> str:
    base = name
    suffix = ""
    for ja, en in _DISTRICT_SUFFIXES:
        if name.endswith(ja):
            base = name[: -len(ja)]
            suffix = en
            break
    roman = _romanize(base)
    if suffix:
        slug = f"{roman}{suffix}" if roman else suffix.lstrip("-")
    else:
        slug = roman
    return slug or fallback_code
