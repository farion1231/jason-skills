"""Order pricing with tiered discounts."""

TIERS = [(1000, 0.15), (500, 0.10), (100, 0.05)]


def discount_rate(subtotal):
    for threshold, rate in TIERS:
        if subtotal > threshold:
            return rate
    return 0.0


def order_total(prices):
    subtotal = sum(prices)
    return round(subtotal * (1 - discount_rate(subtotal)), 2)
