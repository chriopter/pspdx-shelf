"""The two PSPDX schemas, vendored, and a validator that checks formats:
jsonschema passes date-time and uri unread unless the format checkers are
installed, so their absence is an error here, not a silent pass."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

import jsonschema

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG_SCHEMA_URL = "https://chriopter.github.io/pspdx/schema/catalog-v1.json"
PSPDX_SCHEMA_URL = "https://chriopter.github.io/pspdx/schema/pspdx-v1.json"
FORMATS = ("date-time", "uri", "uri-reference")


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict[str, Any]:
    """Load a vendored JSON schema by filename."""
    with open(os.path.join(HERE, "schema", name), encoding="utf-8") as f:
        return json.load(f)


def _validator(name: str):
    schema = load_schema(name)
    cls = jsonschema.validators.validator_for(schema)
    cls.check_schema(schema)
    checker = cls.FORMAT_CHECKER
    missing = [fmt for fmt in FORMATS if fmt not in checker.checkers]
    if missing:
        raise RuntimeError(f"no checker for format {', '.join(missing)}; "
                           "install rfc3339-validator and rfc3986-validator")
    return cls(schema, format_checker=checker)


def problems(document: Any, name: str) -> list[str]:
    """Every place document breaks the schema, in document order."""
    def order(error):
        return [(0, p, "") if isinstance(p, int) else (1, 0, p) for p in error.absolute_path]
    errors = _validator(name).iter_errors(document)
    return [f"{e.json_path}: {e.message}" for e in sorted(errors, key=order)]


def catalog_problems(catalog: Any) -> list[str]:
    """Return catalog-v1 validation problems."""
    return problems(catalog, "catalog-v1.json")


def manifest_problems(manifest: Any) -> list[str]:
    """Return pspdx-v1 validation problems."""
    return problems(manifest, "pspdx-v1.json")
