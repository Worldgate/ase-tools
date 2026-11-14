"""Helpers for decoded property lists."""

import math


def props_to_dict(props):
    """Indexed properties (Colors[0..5], stats[0..11]) become {index: value}."""
    out = {}
    for name, idx, _t, val in props:
        if idx == 0 and name not in out:
            out[name] = val
        else:
            cur = out.get(name)
            if not isinstance(cur, dict) or "_idx" not in cur:
                cur = {"_idx": True, 0: cur} if name in out else {"_idx": True}
                out[name] = cur
            cur[idx] = val
    return out


def indexed(p, name, count, default=0):
    v = p.get(name)
    if v is None:
        return [default] * count
    if isinstance(v, dict) and v.get("_idx"):
        return [v.get(i, default) for i in range(count)]
    return [v] + [default] * (count - 1)


def clean_json(v):
    """Drop the internal _idx markers, and turn NaN/inf (not valid JSON) into null."""
    if isinstance(v, dict):
        return {str(k): clean_json(x) for k, x in v.items() if k != "_idx"}
    if isinstance(v, list):
        return [clean_json(x) for x in v]
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v
