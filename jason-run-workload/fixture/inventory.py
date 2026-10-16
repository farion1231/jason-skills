"""In-memory inventory management."""


class Inventory:
    def __init__(self):
        self._stock = {}

    def add(self, sku, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        self._stock[sku] = self._stock.get(sku, 0) + qty

    def remove(self, sku, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        current = self._stock.get(sku, 0)
        self._stock[sku] = current - qty
        return self._stock[sku]

    def available(self, sku):
        return self._stock.get(sku, 0)

    def low_stock(self, threshold):
        return sorted(sku for sku, qty in self._stock.items() if qty < threshold)
