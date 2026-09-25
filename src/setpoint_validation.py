"""Shared validation rules for EVSE active, reactive and CosPhi setpoints."""

from __future__ import annotations

import math


MAX_REACTIVE_VAR = 11000
MIN_COSPHI = -0.99
MAX_COSPHI = 1.0


def finite_number(value, field: str) -> float:
    """Convert *value* to a finite float, with an operator-facing error."""
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a valid numeric value.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite numeric value.")
    return number


def validate_active_power(value, pn_limit) -> int:
    """Validate P against the active Pn limit and return rounded watts."""
    active = finite_number(value, "Active P")
    pn = finite_number(pn_limit, "Pn")
    if pn <= 0:
        raise ValueError("Pn must be greater than 0 W before sending a setpoint.")
    if abs(active) > pn:
        raise ValueError(f"Active P must stay within +/-{int(pn)} W (Pn).")
    return int(round(active))


def validate_reactive_power(value, *, optional: bool = False) -> int | None:
    """Validate Q and preserve an intentionally omitted optional value."""
    raw = "" if value is None else str(value).strip()
    if optional and not raw:
        return None
    reactive = finite_number(raw, "Reactive Q")
    if abs(reactive) > MAX_REACTIVE_VAR:
        raise ValueError(f"Reactive Q must stay within +/-{MAX_REACTIVE_VAR} var.")
    return int(round(reactive))


def validate_cosphi(value, *, default: float = 1.0) -> float:
    """Validate CosPhi. Zero is deliberately excluded for EVSE setpoints."""
    raw = "" if value is None else str(value).strip()
    cosphi = default if not raw else finite_number(raw, "CosPhi")
    if not MIN_COSPHI <= cosphi <= MAX_COSPHI or cosphi == 0:
        raise ValueError(
            "CosPhi must be between -0.99 and 1.00; value 0 is not allowed."
        )
    return cosphi
