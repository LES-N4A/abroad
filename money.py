"""Money is stored as integer millimes (1 DT = 1000 millimes) everywhere."""

MILLIMES_PER_DT = 1000


def to_millimes(value, default=0):
    """Parse a dinars input ("12.5", 12.5) into integer millimes."""
    if value is None or value == "":
        return default
    if isinstance(value, int):
        return value * MILLIMES_PER_DT
    text = str(value).strip().replace(" ", "").replace(",", ".")
    if not text:
        return default
    try:
        return int(round(float(text) * MILLIMES_PER_DT))
    except (TypeError, ValueError):
        return default


def from_millimes(value):
    """Millimes -> dinars as a float, for display helpers that need a number."""
    try:
        return int(value or 0) / MILLIMES_PER_DT
    except (TypeError, ValueError):
        return 0.0


def format_dt(value, decimals=0):
    """Format millimes as a readable dinars string, e.g. '1 250 DT'."""
    amount = from_millimes(value)
    if decimals:
        return f"{amount:,.{decimals}f} DT"
    return f"{amount:,.0f} DT"
