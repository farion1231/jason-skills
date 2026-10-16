# MiniShop

A small inventory + pricing library. This project is a **fixed workload fixture** for
cc-switch proxy testing — identical on every run so baseline comparisons stay valid.

Modules:

- `inventory.py` — in-memory stock management
- `pricing.py` — order totals with tiered discounts
- `coupons.py` — coupon validation and application
- `shipping.py` — weight-tiered shipping costs with a free-shipping threshold
- `orders.py` — order placement combining inventory, pricing, coupons and shipping
- `report.py` — sales reporting helpers

Run the test suite:

```bash
python3 -m unittest -v
```
