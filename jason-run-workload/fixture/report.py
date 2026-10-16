"""Sales reporting helpers."""


def top_seller(sales):
    best = max(sales, key=lambda s: s["qty"])
    return best["sku"]


def total_units(sales):
    return sum(s["qty"] for s in sales)
