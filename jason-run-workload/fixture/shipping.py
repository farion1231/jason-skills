"""Shipping cost calculation: weight-tiered rates, free above a subtotal threshold."""

FREE_SHIPPING_THRESHOLD = 100

RATES = [(5, 8.0), (20, 12.0)]  # (max_kg exclusive, cost); heavier falls through
OVERWEIGHT_COST = 25.0


def shipping_cost(subtotal, weight_kg):
    if subtotal >= FREE_SHIPPING_THRESHOLD:
        return 0.0
    if weight_kg < 0:
        raise ValueError("weight must be non-negative")
    for max_kg, cost in RATES:
        if weight_kg < max_kg:
            return cost
    return OVERWEIGHT_COST
