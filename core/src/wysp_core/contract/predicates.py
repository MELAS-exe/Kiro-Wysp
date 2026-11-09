"""The predicate language: parsing, safe placeholder substitution and evaluation.

A predicate is a JSON object: a comparison on a JMESPath expression, or a combination
(`all`, `any`, `not`). The same language serves action postconditions, exercise success criteria
and verification goals. Evaluation is pure and returns the actual and expected values, which are
the raw material of the evidence shown to the user.

Placeholders `${params.x}` and `${bindings.x}` are replaced before evaluation:
* in `ref` and `value`, anywhere in a string;
* in `path`, ONLY inside single-quoted JMESPath raw literals, where the value is escaped.
Any other position is rejected, so a parameter value can never inject JMESPath syntax.
Values containing a backslash or a control character are rejected in `path` literals.
"""

from __future__ import annotations

import re
from typing import Any

import jmespath
from jmespath.exceptions import JMESPathError
from pydantic import BaseModel, TypeAdapter, ValidationError

from .actions import Predicate, PredicateOutcome
from .observation import Observation

PLACEHOLDER_RE = re.compile(r"\$\{(params|bindings)\.([A-Za-z_][A-Za-z0-9_]*)\}")
MAX_REGEX_LEN = 200
MAX_REGEX_SUBJECT = 1000

_adapter: TypeAdapter[Predicate] = TypeAdapter(Predicate)


class PredicateError(ValueError):
    """Raised for malformed predicates or unsafe substitutions."""


# ------------------------------------------------------------------------------------ parsing
def to_dict(predicate: Any) -> dict[str, Any]:
    if isinstance(predicate, BaseModel):
        return predicate.model_dump(by_alias=True, mode="json")
    if isinstance(predicate, dict):
        return predicate
    raise PredicateError(f"not a predicate: {type(predicate).__name__}")


def parse(predicate: Any) -> dict[str, Any]:
    """Validate the structure and return the predicate in plain-dict form (aliases preserved)."""
    raw = to_dict(predicate)
    try:
        model = _adapter.validate_python(raw)
    except ValidationError as exc:
        raise PredicateError(f"invalid predicate: {exc.errors()[0]['msg']} at {exc.errors()[0]['loc']}") from exc
    out = model.model_dump(by_alias=True, mode="json", exclude_unset=True)
    _check_paths(out)
    return out


def _walk_compares(pred: dict[str, Any]):
    if "all" in pred:
        for p in pred["all"]:
            yield from _walk_compares(p)
    elif "any" in pred:
        for p in pred["any"]:
            yield from _walk_compares(p)
    elif "not" in pred:
        yield from _walk_compares(pred["not"])
    else:
        yield pred


def _check_paths(pred: dict[str, Any]) -> None:
    for cmp in _walk_compares(pred):
        path = cmp["path"]
        # Replace valid in-literal placeholders with a dummy to check syntax and placement.
        _scan_path(path, lambda _kind, _name: "x")
        probe = _scan_path(path, lambda _kind, _name: "x")
        try:
            jmespath.compile(probe)
        except JMESPathError as exc:
            raise PredicateError(f"invalid JMESPath {path!r}: {exc}") from exc
        ref = cmp.get("ref")
        if isinstance(ref, str) and "${" in ref and not PLACEHOLDER_RE.search(ref):
            raise PredicateError(f"malformed placeholder in ref {ref!r}")


# ----------------------------------------------------------------------------- substitution
def _scan_path(path: str, resolve) -> str:
    """Walk a JMESPath string. Placeholders are only allowed inside single-quoted raw literals."""
    out: list[str] = []
    i, n = 0, len(path)
    in_lit = False
    while i < n:
        ch = path[i]
        if not in_lit:
            if path.startswith("${", i):
                raise PredicateError(f"placeholder outside a quoted literal in path {path!r}")
            if ch == "'":
                in_lit = True
            out.append(ch)
            i += 1
            continue
        # inside a raw literal
        if ch == "\\" and i + 1 < n and path[i + 1] in ("'", "\\"):
            out.append(path[i : i + 2])
            i += 2
        elif ch == "'":
            in_lit = False
            out.append(ch)
            i += 1
        elif path.startswith("${", i):
            m = PLACEHOLDER_RE.match(path, i)
            if not m:
                raise PredicateError(f"malformed placeholder in path {path!r}")
            out.append(_escape_literal(str(resolve(m.group(1), m.group(2)))))
            i = m.end()
        else:
            out.append(ch)
            i += 1
    if in_lit:
        raise PredicateError(f"unterminated literal in path {path!r}")
    return "".join(out)


def _escape_literal(value: str) -> str:
    if "\\" in value or any(ord(c) < 32 for c in value):
        raise PredicateError("value contains a backslash or control character and cannot be used in a path literal")
    return value.replace("'", "\\'")


def _sub_value(value: Any, scopes: dict[str, dict[str, Any]]) -> Any:
    if isinstance(value, str):
        m = PLACEHOLDER_RE.fullmatch(value)
        if m:
            return _lookup(scopes, m.group(1), m.group(2))
        return PLACEHOLDER_RE.sub(lambda mm: str(_lookup(scopes, mm.group(1), mm.group(2))), value)
    if isinstance(value, list):
        return [_sub_value(v, scopes) for v in value]
    if isinstance(value, dict):
        return {k: _sub_value(v, scopes) for k, v in value.items()}
    return value


def _lookup(scopes: dict[str, dict[str, Any]], kind: str, name: str) -> Any:
    scope = scopes.get(kind, {})
    if name not in scope:
        raise PredicateError(f"unknown placeholder ${{{kind}.{name}}}")
    return scope[name]


def substitute(
    predicate: Any, params: dict[str, Any] | None = None, bindings: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Replace placeholders and return a new plain-dict predicate."""
    scopes = {"params": params or {}, "bindings": bindings or {}}
    return _substitute(to_dict(predicate), scopes)


def _substitute(pred: dict[str, Any], scopes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if "all" in pred:
        return {"all": [_substitute(p, scopes) for p in pred["all"]]}
    if "any" in pred:
        return {"any": [_substitute(p, scopes) for p in pred["any"]]}
    if "not" in pred:
        return {"not": _substitute(pred["not"], scopes)}
    out = dict(pred)
    out["path"] = _scan_path(pred["path"], lambda kind, name: _lookup(scopes, kind, name))
    if pred.get("ref") is not None:
        out["ref"] = _sub_value(pred["ref"], scopes)
    if "value" in pred:
        out["value"] = _sub_value(pred["value"], scopes)
    return out


# ------------------------------------------------------------------------------- evaluation
def evaluate(predicate: Any, observation: Observation) -> PredicateOutcome:
    """Evaluate a (placeholder-free) predicate on an observation."""
    raw = to_dict(predicate)
    obs_json = observation.model_dump(mode="json", by_alias=True)
    return _eval(raw, obs_json)


def _eval(pred: dict[str, Any], obs_json: dict[str, Any]) -> PredicateOutcome:
    if "all" in pred:
        kids = [_eval(p, obs_json) for p in pred["all"]]
        return PredicateOutcome(ok=all(k.ok for k in kids), op="all", children=kids)
    if "any" in pred:
        kids = [_eval(p, obs_json) for p in pred["any"]]
        return PredicateOutcome(ok=any(k.ok for k in kids), op="any", children=kids)
    if "not" in pred:
        kid = _eval(pred["not"], obs_json)
        return PredicateOutcome(ok=not kid.ok, op="not", children=[kid])
    return _compare(pred, obs_json)


def _compare(cmp: dict[str, Any], obs_json: dict[str, Any]) -> PredicateOutcome:
    path, op, expected = cmp["path"], cmp["op"], cmp.get("value")
    if "${" in path:
        raise PredicateError("predicate still contains placeholders; call substitute() first")
    target: Any = obs_json
    ref = cmp.get("ref")
    if ref is not None:
        target = next((e for e in obs_json["entities"] if e["ref"] == ref), None)
        if target is None:
            ok = op == "not_exists"
            return PredicateOutcome(ok=ok, path=f"{ref} :: {path}", op=op, actual=None, expected=expected)
    try:
        actual = jmespath.search(path, target)
    except JMESPathError as exc:
        raise PredicateError(f"invalid JMESPath {path!r}: {exc}") from exc
    return PredicateOutcome(
        ok=_apply(op, actual, expected),
        path=path if ref is None else f"{ref} :: {path}",
        op=op,
        actual=actual,
        expected=expected,
    )


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _apply(op: str, actual: Any, expected: Any) -> bool:
    match op:
        case "exists":
            return actual is not None
        case "not_exists":
            return actual is None
        case "eq":
            return actual == expected
        case "ne":
            return actual != expected
        case "gt" | "gte" | "lt" | "lte":
            if not (_is_num(actual) and _is_num(expected)):
                return False
            return {"gt": actual > expected, "gte": actual >= expected, "lt": actual < expected, "lte": actual <= expected}[op]
        case "in":
            return isinstance(expected, list) and actual in expected
        case "contains":
            if isinstance(actual, (list, str)):
                return expected in actual if not isinstance(actual, str) or isinstance(expected, str) else False
            return False
        case "matches":
            if not (isinstance(actual, str) and isinstance(expected, str)):
                return False
            if len(expected) > MAX_REGEX_LEN or len(actual) > MAX_REGEX_SUBJECT:
                return False
            return re.fullmatch(expected, actual) is not None
        case "len_eq" | "len_gte":
            if not isinstance(actual, (list, dict, str)) or not _is_num(expected):
                return False
            return len(actual) == expected if op == "len_eq" else len(actual) >= expected
    return False
