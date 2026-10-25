"""Data shapes passed between checkers, filters, state and notifiers."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StoreStock:
    store_id: str
    name: str
    distance: float | None = None
    qty: int | None = None
    address: str = ""
    pickup: bool | None = None   # True: order online now, pick up at this store
    zip: str = ""
    lat: float | None = None
    lon: float | None = None
    level: str = ""              # retailer's own stock word when it has no count: "high", "low"
    via_area: str = ""           # the area the retailer was asked about (its distance is from that ZIP)
    area: str = ""               # the closest of your areas that contains this store
    chain: str = ""              # chain key for store exclusions (target, bestbuy, kroger)

    @property
    def low(self) -> bool:
        return self.level == "low" or (self.qty is not None and 0 < self.qty <= 2)

    def stock_text(self) -> str:
        if self.qty:
            return f"{self.qty} in stock"
        if self.level:
            return {"high": "plenty in stock", "low": "low stock"}.get(self.level.lower(), f"{self.level} stock")
        return "in stock"

    def label(self) -> str:
        bits = [self.name or f"Store {self.store_id}"]
        if self.distance is not None:
            bits.append(f"{self.distance:.1f} mi")
        if self.qty:
            bits.append(f"qty {self.qty}")
        elif self.level:
            bits.append(f"{self.level} stock")
        if self.pickup:
            bits.append("pickup")
        elif self.pickup is False:
            bits.append("in store only")
        return " | ".join(bits)


@dataclass
class StockResult:
    retailer: str               # internal id: bestbuy, target, walmart, walgreens, cvs, web
    retailer_name: str          # display name
    product_id: str
    title: str
    url: str
    price: float | None = None
    upc: str | None = None
    online: bool = False
    online_status: str = ""
    stores: list[StoreStock] = field(default_factory=list)
    third_party: bool | None = None   # True when sold by a marketplace seller
    image: str | None = None
    source: str = "watch"             # "watch", "search: <name>" or "auto"
    type_key: str | None = None       # product type from the classifier (etb, booster_bundle, ...)
    type_label: str = ""
    preorder: bool = False
    confirmed: bool = False           # re-checked before alerting
    watch_name: str | None = None
    msrp: float | None = None
    note: str = ""

    @property
    def key(self) -> str:
        return f"{self.retailer}:{self.product_id}"

    @property
    def pickup_stores(self) -> list[StoreStock]:
        return [s for s in self.stores if s.pickup]

    @property
    def in_stock(self) -> bool:
        return self.online or bool(self.stores)

    def status_text(self) -> str:
        parts = []
        if self.online:
            parts.append(f"Online: {self.online_status or 'in stock'}")
        if self.stores:
            pick = len(self.pickup_stores)
            parts.append(f"{len(self.stores)} store(s)" + (f", pickup at {pick}" if pick else ""))
        return ", ".join(parts) if parts else (self.online_status or "Out of stock")
