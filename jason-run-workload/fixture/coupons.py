"""Coupon validation and application. Coupon codes are case-insensitive."""

COUPONS = {
    "SAVE10": {"kind": "percent", "value": 10, "min_subtotal": 50},
    "SAVE25": {"kind": "percent", "value": 25, "min_subtotal": 200},
    "FLAT20": {"kind": "flat", "value": 20, "min_subtotal": 100},
}


def lookup(code):
    coupon = COUPONS.get(code)
    if coupon is None:
        raise KeyError(f"unknown coupon: {code}")
    return coupon


def apply_coupon(code, subtotal):
    coupon = lookup(code)
    if subtotal < coupon["min_subtotal"]:
        return subtotal
    if coupon["kind"] == "percent":
        return round(subtotal * (1 - coupon["value"] / 100), 2)
    return round(subtotal - coupon["value"], 2)
