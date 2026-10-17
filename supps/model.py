"""The one record everything is reduced to: a product size at a shop, at the moment we looked."""

from dataclasses import asdict, dataclass, field


@dataclass
class Variant:
    """One purchasable variant as the shop lists it (flavour × size)."""

    label: str
    grams: float | None
    price: float
    list_price: float | None = None
    available: bool | None = True


@dataclass
class Offer:
    shop: str  # source id, e.g. "nutrimuscle"
    market: str  # ES / FR / EU (ships to both from elsewhere)
    kind: str  # creatine / whey
    product: str
    url: str
    grams: float
    price: float  # cheapest in-stock flavour of this size, EUR incl. VAT
    list_price: float | None = None  # crossed-out price when on sale
    available: bool | None = True
    flavours: int = 1
    brand: str | None = None
    seller: str | None = None  # marketplace seller when not the shop itself
    creapure: bool = False
    whey_type: str | None = None  # concentrate / isolate / blend / hydrolysed
    native: bool = False
    protein_100g: float | None = None
    unflavoured: bool = False
    sweetener_free: bool = False
    tested: bool = False  # Informed Sport/Choice, Kölner Liste
    method: str = "feed"  # feed / page / browser / reviewed
    note: str = ""
    captured_at: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.shop}|{self.url}|{int(self.grams)}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["eur_kg"] = round(self.price / self.grams * 1000, 2)
        if self.kind == "whey" and self.protein_100g:
            d["eur_kg_protein"] = round(d["eur_kg"] / (self.protein_100g / 100), 2)
        if not d["extra"]:
            d.pop("extra")
        return d


def group_variants(variants: list[Variant]) -> dict[float, dict]:
    """Size → cheapest in-stock variant price, flavour count, list price, availability.

    When no flavour of a size is in stock, the size is kept as unavailable with its lowest price.
    """
    sizes: dict[float, dict] = {}
    for v in variants:
        if not v.grams or v.price <= 0:
            continue
        s = sizes.setdefault(v.grams, {"in": [], "out": [], "labels": set()})
        s["labels"].add(v.label)
        (s["out"] if v.available is False else s["in"]).append(v)
    out = {}
    for g, s in sizes.items():
        pool = s["in"] or s["out"]
        best = min(pool, key=lambda v: v.price)
        out[g] = {
            "price": best.price,
            "list_price": best.list_price if best.list_price and best.list_price > best.price + 0.01 else None,
            "available": bool(s["in"]) if s["in"] or any(v.available is False for v in s["out"]) else None,
            "flavours": max(1, len(s["labels"])),
            "labels": sorted(s["labels"]),
        }
    return out
