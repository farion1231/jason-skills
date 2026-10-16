"""MiniShop test suite. The tests describe correct behavior — do not modify them."""

import unittest

from coupons import apply_coupon
from inventory import Inventory
from orders import place_order
from pricing import discount_rate, order_total
from report import top_seller, total_units
from shipping import shipping_cost


class TestInventory(unittest.TestCase):
    def test_add_and_available(self):
        inv = Inventory()
        inv.add("widget", 5)
        inv.add("widget", 3)
        self.assertEqual(inv.available("widget"), 8)

    def test_add_rejects_nonpositive(self):
        inv = Inventory()
        with self.assertRaises(ValueError):
            inv.add("widget", 0)

    def test_remove_decrements(self):
        inv = Inventory()
        inv.add("widget", 5)
        self.assertEqual(inv.remove("widget", 2), 3)

    def test_remove_rejects_overdraw(self):
        inv = Inventory()
        inv.add("widget", 3)
        with self.assertRaises(ValueError):
            inv.remove("widget", 5)

    def test_low_stock_sorted(self):
        inv = Inventory()
        inv.add("b", 2)
        inv.add("a", 1)
        inv.add("c", 50)
        self.assertEqual(inv.low_stock(10), ["a", "b"])


class TestPricing(unittest.TestCase):
    def test_no_discount_below_first_tier(self):
        self.assertEqual(discount_rate(50), 0.0)

    def test_discount_applies_at_exact_boundary(self):
        self.assertEqual(discount_rate(500), 0.10)
        self.assertEqual(discount_rate(1000), 0.15)

    def test_order_total_mid_tier(self):
        # 600 is safely inside the 10% tier regardless of boundary handling
        self.assertEqual(order_total([200, 400]), 540.0)


class TestReport(unittest.TestCase):
    def test_top_seller_basic(self):
        sales = [
            {"sku": "a", "qty": 3},
            {"sku": "b", "qty": 9},
            {"sku": "c", "qty": 1},
        ]
        self.assertEqual(top_seller(sales), "b")

    def test_top_seller_empty_returns_none(self):
        self.assertIsNone(top_seller([]))

    def test_total_units(self):
        sales = [{"sku": "a", "qty": 3}, {"sku": "b", "qty": 9}]
        self.assertEqual(total_units(sales), 12)


class TestCoupons(unittest.TestCase):
    def test_percent_coupon_applies(self):
        self.assertEqual(apply_coupon("SAVE10", 80), 72.0)

    def test_flat_coupon_applies(self):
        self.assertEqual(apply_coupon("FLAT20", 150), 130.0)

    def test_below_minimum_no_discount(self):
        self.assertEqual(apply_coupon("SAVE25", 100), 100)

    def test_unknown_coupon_raises(self):
        with self.assertRaises(KeyError):
            apply_coupon("NOPE", 100)

    def test_coupon_code_case_insensitive(self):
        self.assertEqual(apply_coupon("save10", 80), 72.0)


class TestShipping(unittest.TestCase):
    def test_light_package_rate(self):
        self.assertEqual(shipping_cost(50, 2), 8.0)

    def test_medium_package_rate(self):
        self.assertEqual(shipping_cost(50, 10), 12.0)

    def test_overweight_rate(self):
        self.assertEqual(shipping_cost(50, 30), 25.0)

    def test_free_shipping_at_threshold(self):
        self.assertEqual(shipping_cost(100, 5), 0.0)

    def test_negative_weight_rejected(self):
        with self.assertRaises(ValueError):
            shipping_cost(50, -1)

    def test_negative_weight_rejected_even_when_free_shipping(self):
        with self.assertRaises(ValueError):
            shipping_cost(150, -1)


class TestOrders(unittest.TestCase):
    def test_place_order_happy_path(self):
        inv = Inventory()
        inv.add("a", 10)
        inv.add("b", 5)
        total = place_order(inv, [("a", 2, 30.0), ("b", 1, 20.0)], weight_kg=3)
        self.assertEqual(total, 88.0)
        self.assertEqual(inv.available("a"), 8)

    def test_place_order_coupon_and_free_shipping(self):
        inv = Inventory()
        inv.add("c", 3)
        total = place_order(inv, [("c", 1, 180.0)], coupon="SAVE10", weight_kg=2)
        self.assertEqual(total, 153.9)

    def test_place_order_rolls_back_on_shortage(self):
        inv = Inventory()
        inv.add("a", 5)
        inv.add("b", 1)
        with self.assertRaises(ValueError):
            place_order(inv, [("a", 2, 10.0), ("b", 3, 5.0)])
        self.assertEqual(inv.available("a"), 5)


if __name__ == "__main__":
    unittest.main()
