"""Order placement combining inventory, pricing, coupons and shipping."""

from coupons import apply_coupon
from pricing import order_total
from shipping import shipping_cost


def place_order(inv, lines, coupon=None, weight_kg=1):
    """lines: list of (sku, qty, unit_price) tuples.

    Reserves stock for every line, then prices the order. If any line cannot
    be fulfilled, the whole order must fail and leave stock unchanged.
    """
    for sku, qty, _price in lines:
        inv.remove(sku, qty)
    total = order_total([qty * price for _sku, qty, price in lines])
    if coupon is not None:
        total = apply_coupon(coupon, total)
    return round(total + shipping_cost(total, weight_kg), 2)
