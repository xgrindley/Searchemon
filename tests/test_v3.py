"""Tests for areas, store discovery, product discovery, new stores and accuracy checks.

All offline: retailer and map responses are canned. Run: python -m unittest discover tests
"""
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# A tiny stand-in for the zipcodes package (the real one ships every US ZIP).
ZIPS = {
    "89431": ("39.5400", "-119.7480", "ANYTOWN", "NV"),
    "89502": ("39.4950", "-119.7740", "RENO", "NV"),
    "96150": ("38.9170", "-119.9860", "SOUTH LAKE TAHOE", "CA"),
    "10001": ("40.7500", "-73.9970", "NEW YORK", "NY"),
}
stub = types.ModuleType("zipcodes")
stub.matching = lambda z: [{"zip_code": z, "lat": ZIPS[z][0], "long": ZIPS[z][1], "city": ZIPS[z][2], "state": ZIPS[z][3]}] if z in ZIPS else []
sys.modules["zipcodes"] = stub

from restock import geo  # noqa: E402
from restock.catalog import Catalog  # noqa: E402
from restock.config import load_config  # noqa: E402
from restock.engine import Monitor  # noqa: E402
from restock.models import StockResult, StoreStock  # noqa: E402
from restock.places import Place, PlaceFinder, parse_overpass  # noqa: E402
from restock.retailers.blocks import classify as classify_block  # noqa: E402
from restock.retailers.browser import FetchResult  # noqa: E402
from restock.retailers.kroger import Kroger, kroger_product_ids  # noqa: E402
from restock.retailers.pages import PokemonCenter, parse_amazon  # noqa: E402
from restock.retailers.walmart import Walmart  # noqa: E402

geo.zip_point.cache_clear()

BASE_CFG = """
discord: {webhooks: {default: "https://discord.com/api/webhooks/1/abc"}}
areas:
  - {name: Home, zip: "89431", radius_miles: 10}
  - {name: Tahoe, zip: "96150", radius_miles: 5}
settings: {windows_toast: false, alert_on_startup: true}
discovery: {enabled: false, places: false}
retailers:
  target: {enabled: false}
  walmart: {enabled: false}
  pokemoncenter: {enabled: false}
  gamestop: {enabled: false}
  costco: {enabled: false}
  samsclub: {enabled: false}
  barnesandnoble: {enabled: false}
  booksamillion: {enabled: false}
  amazon: {enabled: false}
  dicks: {enabled: false}
  safeway: {enabled: false}
  raleys: {enabled: false}
  walgreens: {enabled: false}
  cvs: {enabled: false}
  web: {enabled: false}
"""


class Base(unittest.TestCase):
    extra = ""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg_path = os.path.join(self.dir, "config.yaml")
        with open(self.cfg_path, "w") as fh:
            fh.write(BASE_CFG + self.extra)
        self.posts = []
        self.patches = [
            mock.patch("restock.notify.requests.post", side_effect=lambda url, json=None, timeout=None:
                       (self.posts.append(json), mock.Mock(status_code=204))[1]),
            mock.patch("restock.retailers.base.Retailer.pause"),
            mock.patch("restock.engine.Monitor.pause_between_checks"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        import logging
        for h in list(logging.getLogger("restock").handlers):
            h.close()
            logging.getLogger("restock").removeHandler(h)
        shutil.rmtree(self.dir, ignore_errors=True)


class GeoTests(Base):
    def test_areas_and_distance(self):
        cfg = load_config(self.cfg_path)
        self.assertEqual([a.name for a in cfg.areas], ["Home", "Tahoe"])
        self.assertTrue(all(a.located for a in cfg.areas))
        d = geo.miles(geo.zip_point("89431"), geo.zip_point("89502"))
        self.assertTrue(2 < d < 5, d)
        self.assertEqual(geo.zip_place("89431"), "Anytown, NV")
        area, dist = geo.nearest_area(geo.zip_point("89502"), cfg.areas)
        self.assertEqual(area.name, "Home")
        area, _ = geo.nearest_area(geo.zip_point("10001"), cfg.areas)
        self.assertIsNone(area)
        # Unknown point: the retailer's own distance from the area it was asked about decides.
        area, dist = geo.nearest_area(None, cfg.areas, 4.0, cfg.areas[1])
        self.assertEqual((area.name, dist), ("Tahoe", 4.0))

    def test_old_single_location_still_works(self):
        with open(self.cfg_path, "w") as fh:
            fh.write("location: {zip: '89502', radius_miles: 12}\n")
        cfg = load_config(self.cfg_path)
        self.assertEqual((cfg.areas[0].name, cfg.areas[0].zip, cfg.areas[0].radius), ("Home", "89502", 12.0))

    def test_localize_filters_stores(self):
        with open(self.cfg_path, "a") as fh:
            fh.write("  kroger: {enabled: false}\n")
        mon = Monitor(self.cfg_path)
        mon.cfg.raw["settings"]["excluded_stores"] = ["target:3"]
        mon.cfg.raw["settings"]["min_store_qty"] = 2
        res = StockResult("target", "Target", "1", "ETB", "u", stores=[
            StoreStock("1", "Reno", qty=4, zip="89502", via_area="Home"),          # 3 mi from Home: kept
            StoreStock("2", "NYC", qty=4, zip="10001", via_area="Home"),           # far: dropped
            StoreStock("3", "Anytown East", qty=4, zip="10001", via_area="Home"),   # excluded by you
            StoreStock("4", "Anytown 1 unit", qty=1, zip="89431", via_area="Home"),  # below min qty
            StoreStock("5", "Tahoe", qty=3, zip="96150", via_area="Tahoe"),         # inside Tahoe area
        ])
        mon.localize(res)
        self.assertEqual([(s.store_id, s.area) for s in res.stores], [("5", "Tahoe"), ("1", "Home")])
        self.assertLess(res.stores[0].distance, 1)


class PlacesTests(Base):
    OVERPASS = {"elements": [
        {"type": "way", "center": {"lat": 39.5401, "lon": -119.7481},
         "tags": {"shop": "department_store", "brand": "Target", "name": "Target", "addr:city": "Anytown", "addr:postcode": "89431"}},
        {"type": "node", "lat": 39.54012, "lon": -119.74812,
         "tags": {"amenity": "pharmacy", "brand": "CVS Pharmacy", "name": "CVS Pharmacy"}},   # counter inside Target
        {"type": "node", "lat": 39.53, "lon": -119.77, "tags": {"amenity": "pharmacy", "brand": "Walmart", "name": "Walmart Pharmacy"}},
        {"type": "node", "lat": 39.52, "lon": -119.76, "tags": {"shop": "video_games", "brand": "GameStop", "name": "GameStop"}},
        {"type": "node", "lat": 39.521, "lon": -119.761, "tags": {"amenity": "fuel", "brand": "Sam's Club", "name": "Sam's Club Gas"}},
        {"type": "node", "lat": 39.50, "lon": -119.79, "tags": {"shop": "books", "brand": "Barnes & Noble", "name": "Barnes & Noble"}},
        {"type": "node", "lat": 39.51, "lon": -119.78, "tags": {"shop": "supermarket", "name": "Smith's"}},
        {"type": "node", "lat": 39.512, "lon": -119.781, "tags": {"shop": "supermarket", "name": "Targeted Foods"}},
    ]}

    def test_parse_and_dedupe(self):
        places = parse_overpass(self.OVERPASS)
        chains = sorted(p.chain for p in places)
        self.assertEqual(chains, ["barnesandnoble", "gamestop", "kroger", "target"])

    def test_refresh_merges_chain_finder(self):
        cfg = load_config(self.cfg_path)
        finder = PlaceFinder(cfg.data_dir, mock.Mock())
        chain_source = lambda areas: [Place("target", "Target Anytown", 39.5402, -119.7482, "1 Main", "Anytown", "89431", "2201", "chain")]
        with mock.patch("restock.places.requests.post", return_value=mock.Mock(status_code=200, json=lambda: self.OVERPASS)):
            n = finder.refresh(cfg.areas, [chain_source])
        targets = [p for p in finder.places if p.chain == "target"]
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].store_id, "2201")      # the chain's own record wins over the map's
        self.assertTrue(all(p.area == "Home" for p in finder.places))
        self.assertEqual(n, len(finder.places))
        self.assertFalse(PlaceFinder(cfg.data_dir, mock.Mock()).stale(cfg.areas))   # cached on disk


def kroger_get(url, params=None, headers=None, **kw):
    if url.endswith("/locations"):
        return {"data": [
            {"locationId": "70100123", "chain": "SMITHS", "name": "Smith's Anytown", "address": {"addressLine1": "1 A St", "city": "Anytown", "zipCode": "89431"},
             "geolocation": {"latitude": 39.541, "longitude": -119.749}},
            {"locationId": "70100456", "chain": "SMITHS", "name": "Smith's Reno", "address": {"addressLine1": "2 B St", "city": "Reno", "zipCode": "89502"},
             "geolocation": {"latitude": 39.495, "longitude": -119.774}},
        ]}
    loc = params.get("filter.locationId")
    level = {"70100123": "LOW", "70100456": "TEMPORARILY_OUT_OF_STOCK", None: None}[loc]
    pids = (params.get("filter.productId") or "0082065012345").split(",")
    if "filter.term" in params:
        pids = ["0082065012345", "0082065099999"]
    out = []
    for pid in pids:
        item = {"price": {"regular": 49.99, "promo": 0}, "fulfillment": {"inStore": True, "curbside": True}}
        if level:
            item["inventory"] = {"stockLevel": level}
        out.append({"productId": pid, "upc": "0820650123456" if pid.endswith("2345") else "0820650999999",
                    "brand": "Pokemon", "description": "Pokemon TCG Elite Trainer Box" if pid.endswith("2345") else "Pokemon TCG Card Sleeves",
                    "items": [item]})
    return {"data": out}


class KrogerTests(Base):
    extra = "  kroger: {enabled: true, client_id: id, client_secret: secret, max_stores: 5}\n"

    def test_store_levels_and_upc(self):
        cfg = load_config(self.cfg_path)
        k = Kroger(cfg, mock.Mock())
        k.session.post = mock.Mock(return_value=mock.Mock(status_code=200, json=lambda: {"access_token": "t", "expires_in": 1800}))
        with mock.patch.object(Kroger, "get_json", side_effect=kroger_get):
            res = k.check_ids(["0082065012345"], True)["0082065012345"]
            self.assertEqual([(s.name, s.level, s.pickup) for s in res.stores], [("Smith's Anytown", "low", True)])
            self.assertEqual(res.title, "Pokemon TCG Elite Trainer Box")
            self.assertEqual(k.resolve_upc("820650123456"), "0082065012345")
            self.assertEqual(len(k.search("pokemon trading card game", 10)), 2)
        self.assertEqual(kroger_product_ids("820650123456")[0], "0082065012345")
        k.session.post.assert_called_once()    # token reused


class PageSiteTests(Base):
    AMAZON = """<span id="productTitle"> Pokemon TCG: Mega Evolution Elite Trainer Box </span>
    <div id="corePrice_feature_div"><span class="a-offscreen">$49.99</span></div>
    <div id="availability"><span>In Stock</span></div>
    <input id="add-to-cart-button"><div id="tabular-buybox">Ships from Amazon.com Sold by Amazon.com</div>"""

    def test_amazon(self):
        info = parse_amazon(self.AMAZON)
        self.assertEqual((info["status"], info["price"], info["seller"]), ("in", 49.99, "Amazon.com"))
        reseller = parse_amazon(self.AMAZON.replace("Sold by Amazon.com", "Sold by CardFlipz LLC"))
        self.assertEqual(reseller["seller"], "CardFlipz LLC")
        no_button = parse_amazon(self.AMAZON.replace('<input id="add-to-cart-button">', ""))
        self.assertEqual(no_button["status"], "out")

    def test_queue_signal(self):
        queue_page = "<html><title>Waiting Room</title><p>You are now in line. Estimated wait time: 12 minutes</p></html>"
        self.assertEqual(classify_block(200, queue_page).kind, "queue")
        with open(self.cfg_path, "a") as fh:
            fh.write("  pokemoncenter: {enabled: true, fetch_mode: direct, watch_queue: true}\n")
        mon = Monitor(self.cfg_path)
        pc = mon.retailers["pokemoncenter"]
        pages = iter([queue_page, queue_page, "<html>Shop now</html>", queue_page])
        with mock.patch.object(PokemonCenter, "fetch_html",
                               side_effect=lambda url: FetchResult(200, (t := next(pages)), url, classify_block(200, t))):
            for _ in range(4):
                for sig in pc.signals():
                    mon.handle_signal(sig)
        titles = [p["embeds"][0]["title"] for p in self.posts]
        self.assertEqual(titles, ["Pokemon Center queue is open"])   # once, then the quiet period holds

    def test_walmart_pickup_and_seller(self):
        load_config(self.cfg_path)          # the config must load
        p = {"name": "Pokemon TCG Booster Bundle", "availabilityStatus": "OUT_OF_STOCK", "sellerId": "F55CDC31AB754BB68FE0B39041159D63",
             "priceInfo": {"currentPrice": {"price": 26.94}},
             "fulfillmentOptions": [{"type": "SHIPPING", "availabilityStatus": "OUT_OF_STOCK"},
                                    {"type": "PICKUP", "availabilityStatus": "IN_STOCK", "storeId": "2149", "storeName": "Anytown Supercenter"}]}
        r = Walmart._product_result("1", p, "Walmart")
        self.assertFalse(r.third_party)
        self.assertEqual([(s.store_id, s.pickup) for s in r.stores], [("2149", True)])
        p["sellerName"] = "Poke Flips"
        self.assertTrue(Walmart._product_result("1", p, "Walmart").third_party)


class LocalStoreTests(Base):
    def test_dicks_safeway_raleys(self):
        from restock.retailers import route_url
        from restock.retailers.pages import parse_dicks_listing
        self.assertEqual(route_url("https://www.dickssportinggoods.com/p/pokmon-tcg-x/25abc")[0], "dicks")
        self.assertEqual(route_url("https://www.safeway.com/shop/product-details.970481881.html")[0], "safeway")
        self.assertEqual(route_url("https://www.raleys.com/product/123")[0], "raleys")
        html = ('<a href="/p/pokmon-tcg-prismatic-evolutions-elite-trainer-box-25wjcupkmnprsmtcvxfla/25wjcupkmnprsmtcvxfla"><img></a>'
                '<a href="/p/pokmon-tcg-prismatic-evolutions-elite-trainer-box-25wjcupkmnprsmtcvxfla/25wjcupkmnprsmtcvxfla">'
                'Pok&eacute;mon TCG: Prismatic Evolutions Elite Trainer Box</a>'
                '<a href="/p/pokmon-tcg-mega-evolution-booster-bundle-26abcdefghijklmnop/26abcdefghijklmnop"><img></a>')
        items = dict(parse_dicks_listing(html))
        self.assertEqual(len(items), 2)
        self.assertIn("Prismatic Evolutions Elite Trainer Box", list(items.values())[0])
        self.assertEqual(list(items.values())[1], "Pokemon TCG Mega Evolution Booster Bundle")
        from restock.places import chain_for
        self.assertEqual(chain_for("Safeway", "Safeway").key, "safeway")
        self.assertEqual(chain_for("", "Raley's").key, "raleys")
        self.assertEqual(chain_for("Dick's Sporting Goods", "").key, "dicks")
        self.assertIsNone(chain_for("", "Dick's Wings"))


class CatalogTests(Base):
    def test_merge_new_rotation_groups(self):
        cfg = load_config(self.cfg_path)
        cat = Catalog(cfg.data_dir)
        mk = lambda pid, title, upc=None, r="target": StockResult(r, r.title(), pid, title, f"https://x/{pid}", price=49.99, upc=upc)
        first = [mk("1", "Pokemon TCG Elite Trainer Box", "820650123456"), mk("2", "Pokemon Card Sleeves"),
                 mk("3", "Pokemon TCG Booster Bundle")]
        self.assertEqual(cat.merge("target", first, cfg.raw, mark_run=True), [])          # first run seeds silently
        self.assertEqual(sorted(cat.items), ["target:1", "target:3"])                      # sleeves dropped
        new = cat.merge("target", first + [mk("4", "Pokemon TCG Mini Tin")], cfg.raw, mark_run=True)
        self.assertEqual([n["id"] for n in new], ["4"])
        cat.merge("bestbuy", [mk("9", "Pokémon Trading Card Game: Elite Trainer Box", "0820650123456", "bestbuy")], cfg.raw, mark_run=True)
        etb = [g for g in cat.groups() if g["type_label"] == "Elite Trainer Box"][0]
        self.assertEqual(sorted(l["retailer"] for l in etb["listings"]), ["bestbuy", "target"])   # same UPC, one group
        from restock.tcg import type_settings
        types = type_settings(cfg.raw)
        picks = [cat.rotation("target", 1, types)[0]["id"] for _ in range(3)]
        self.assertEqual(picks, ["3", "1", "4"])           # top-priority types first (bundle, ETB), then round-robin
        cat.set_status("target:3", "ignored")
        self.assertNotIn("3", [i["id"] for i in cat.rotation("target", 5, types)])


class AccuracyTests(Base):
    extra = "  target: {enabled: true}\n"

    def _monitor(self, rechecks):
        mon = Monitor(self.cfg_path)
        r = mon.retailers["target"]
        r.check_ids = mock.Mock(side_effect=rechecks)
        return mon, r

    def test_confirmation_blocks_one_off_glitch(self):
        mon, r = self._monitor([{"1": StockResult("target", "Target", "1", "Pokemon TCG Elite Trainer Box", "u", price=49.99, online=False)}])
        glitch = StockResult("target", "Target", "1", "Pokemon TCG Elite Trainer Box", "u", price=49.99, online=True, online_status="In Stock")
        mon.handle(glitch, None, None, r)
        self.assertEqual(self.posts, [])

    def test_confirmed_restock_alerts(self):
        again = StockResult("target", "Target", "1", "Pokemon TCG Elite Trainer Box", "u", price=49.99, online=True, online_status="In Stock")
        mon, r = self._monitor([{"1": again}])
        first = StockResult("target", "Target", "1", "Pokemon TCG Elite Trainer Box", "u", price=49.99, online=True, online_status="In Stock")
        mon.handle(first, None, None, r)
        self.assertEqual(len(self.posts), 1)
        self.assertIn("Confirmed on a second check.", self.posts[0]["embeds"][0]["description"])
        self.assertEqual(self.posts[0]["embeds"][0]["fields"][1]["value"], "Elite Trainer Box")

    def _field(self, post, name):
        return next((f["value"] for f in post["embeds"][0]["fields"] if f["name"] == name), None)

    def test_alert_shows_msrp_from_product_type(self):
        again = StockResult("target", "Target", "1", "Pokemon TCG Elite Trainer Box", "u", price=49.99, online=True, online_status="In Stock")
        mon, r = self._monitor([{"1": again}])
        first = StockResult("target", "Target", "1", "Pokemon TCG Elite Trainer Box", "u", price=49.99, online=True, online_status="In Stock")
        mon.handle(first, None, None, r)
        msrp = self._field(self.posts[0], "MSRP")
        self.assertIsNotNone(msrp)
        self.assertTrue(msrp.startswith("$"))
        self.assertEqual(self._field(self.posts[0], "Price"), "$49.99")

    def test_alert_msrp_uses_your_type_setting_and_shows_difference(self):
        mon, r = self._monitor([])
        mon.cfg.raw["settings"]["confirm_restocks"] = False
        mon.cfg.raw["product_types"] = {"etb": {"msrp": 45.00}}
        mon.cfg.settings["msrp_tolerance_pct"] = 20
        res = StockResult("target", "Target", "1", "Pokemon TCG Elite Trainer Box", "u", price=49.99, online=True)
        mon.handle(res, None, None, r)
        self.assertEqual(self._field(self.posts[0], "MSRP"), "$45.00 ($4.99 over)")

    def test_alert_msrp_prefers_products_own(self):
        mon, r = self._monitor([])
        mon.cfg.raw["settings"]["confirm_restocks"] = False
        res = StockResult("target", "Target", "1", "Pokemon TCG Elite Trainer Box", "u", price=49.99, online=True, msrp=49.99)
        mon.handle(res, None, None, r)
        self.assertEqual(self._field(self.posts[0], "MSRP"), "$49.99 (at MSRP)")

    def test_msrp_text_cases(self):
        from restock.notify import msrp_text
        self.assertEqual(msrp_text(17.99, 17.99), "$17.99 (at MSRP)")
        self.assertEqual(msrp_text(79.99, 59.99), "$59.99 ($20.00 over)")
        self.assertEqual(msrp_text(4.00, 4.99), "$4.99 ($0.99 under)")
        self.assertEqual(msrp_text(None, 4.99), "$4.99")

    def test_type_switch_and_type_msrp(self):
        mon, r = self._monitor([])
        mon.cfg.raw["settings"]["confirm_restocks"] = False
        mon.cfg.raw["product_types"] = {"booster_pack": {"alert": False}}
        pack = StockResult("target", "Target", "7", "Pokemon TCG Destined Rivals Booster Pack", "u", price=4.99, online=True)
        mon.handle(pack, None, None, r)
        self.assertIn("alerts are off", pack.note)
        pricey = StockResult("target", "Target", "8", "Pokemon TCG Booster Bundle", "u", price=39.99, online=True)
        mon.handle(pricey, None, None, r)
        self.assertIn("over MSRP $26.99", pricey.note)
        self.assertEqual(self.posts, [])


class DiscoveryTests(Base):
    extra = "  target: {enabled: true}\n"

    def test_discovery_tracks_and_announces_new_listings(self):
        with open(self.cfg_path) as fh:
            text = fh.read().replace("discovery: {enabled: false, places: false}",
                                     "discovery: {enabled: true, places: false, retailers: [target], queries: [pokemon tcg], refresh_hours: 6}")
        with open(self.cfg_path, "w") as fh:
            fh.write(text)
        mon = Monitor(self.cfg_path)
        mon.cfg.raw["settings"]["confirm_restocks"] = False
        r = mon.retailers["target"]
        listings = [[StockResult("target", "Target", "11", "Pokemon TCG Elite Trainer Box", "u", price=49.99, online_status="UNCHECKED"),
                     StockResult("target", "Target", "12", "Pokemon Plush Pikachu", "u", price=19.99, online_status="UNCHECKED")],
                    [StockResult("target", "Target", "11", "Pokemon TCG Elite Trainer Box", "u", price=49.99, online_status="UNCHECKED"),
                     StockResult("target", "Target", "13", "Pokemon TCG Ultra Premium Collection", "u", price=119.99, online_status="UNCHECKED")]]
        r.search = mock.Mock(side_effect=lambda q, n: listings.pop(0))
        stock = {"11": True, "13": False}
        r.check_ids = mock.Mock(side_effect=lambda ids, in_store: {
            i: StockResult("target", "Target", i, {"11": "Pokemon TCG Elite Trainer Box", "13": "Pokemon TCG Ultra Premium Collection"}[i],
                           "u", price=49.99, online=stock[i], online_status="In Stock" if stock[i] else "Out Of Stock") for i in ids})
        mon.run_cycle(r)
        self.assertEqual(sorted(mon.catalog.items), ["target:11"])
        self.assertEqual([p["embeds"][0]["title"] for p in self.posts], ["IN STOCK: Pokemon TCG Elite Trainer Box"])
        mon.catalog.runs["target"] -= 7 * 3600     # next catalog search is due
        mon.run_cycle(r)
        self.assertIn("New listing: Pokemon TCG Ultra Premium Collection", [p["embeds"][0]["title"] for p in self.posts])


class PanelV3Tests(Base):
    def test_new_endpoints(self):
        import requests
        from restock.panel import PanelServer
        mon = Monitor(self.cfg_path)
        mon.catalog.merge("target", [StockResult("target", "Target", "1", "Pokemon TCG Elite Trainer Box", "u")], mon.cfg.raw, True)
        mon.places.places = [Place("target", "Target Anytown", 39.54, -119.748, "", "Anytown", "89431", "2201", "chain", "Home", 0.1)]
        panel = PanelServer(mon)
        panel.port = 8796
        self.assertTrue(panel.start())
        s = requests.Session()
        s.trust_env = False
        hdr = {"X-Token": panel.token}
        try:
            g = s.get(panel.url + "api/geo?zip=89502", headers=hdr).json()
            self.assertEqual(g["place"], "Reno, NV")
            self.assertAlmostEqual(g["lat"], 39.495, places=3)
            self.assertEqual(s.get(panel.url + "api/catalog", headers=hdr).json()["groups"][0]["type_label"], "Elite Trainer Box")
            places = s.get(panel.url + "api/places", headers=hdr).json()
            self.assertEqual(places["places"][0]["key"], "target:2201")
            s.post(panel.url + "api/action", json={"action": "exclude_store", "key": "target:2201"}, headers=hdr)
            self.assertIn("target:2201", load_config(self.cfg_path).settings["excluded_stores"])
            s.post(panel.url + "api/action", json={"action": "product_status", "key": "target:1", "status": "ignored"}, headers=hdr)
            self.assertEqual(mon.catalog.items["target:1"]["status"], "ignored")
            types = s.get(panel.url + "api/types", headers=hdr).json()
            self.assertIn("etb", [t["key"] for t in types])
            v = s.post(panel.url + "api/test-filter", json={"title": "Pokemon Card Sleeves", "search": "x"}, headers=hdr).json()
            self.assertFalse(v["is_tcg"])
        finally:
            panel.stop()


if __name__ == "__main__":
    unittest.main()


class RulesTests(unittest.TestCase):
    def test_notification_rules(self):
        import time as _t
        from restock.rules import allow_kind, decide
        st = [StoreStock("1", "Near", distance=3, pickup=True), StoreStock("2", "Far", distance=12, pickup=False)]
        res = StockResult("target", "Target", "9", "ETB", "u", online=True, stores=st)
        d = decide(res, True, ("1", "2"), {})
        self.assertEqual((d.send, d.ping, d.new_online, d.store_ids), (True, True, True, ("1", "2")))
        cfg = {"notify": {"online": False, "pickup_only": True, "max_miles": 10}}
        self.assertEqual(decide(res, True, ("1", "2"), cfg).store_ids, ("1",))
        self.assertFalse(decide(res, True, ("2",), cfg).send)
        self.assertFalse(decide(res, True, ("1",), {"notify": {"retailers": ["walmart"]}}).send)
        night = _t.mktime((2026, 10, 27, 23, 30, 0, 0, 0, -1))
        quiet = {"notify": {"quiet_hours": [{"days": "all", "start": "22:00", "end": "06:00"}]}}
        q = decide(res, True, ("1",), quiet, now=night)
        self.assertEqual((q.send, q.ping), (True, False))
        quiet["notify"]["quiet_mode"] = "skip"
        self.assertFalse(decide(res, True, ("1",), quiet, now=night).send)
        self.assertEqual(allow_kind("new_listing", {}), (True, False))
        self.assertEqual(allow_kind("queue", {"notify": {"queue": False}}), (False, False))


class ImpervaBanTests(unittest.TestCase):
    PAGE = ("<html><body><div>Access denied</div><h1>Error 15</h1><div>www.pokemoncenter.com</div>"
            "<h2>What happened?</h2><p>This request was blocked by our security service</p>"
            "<p>Incident ID: 1-2</p><span>Powered by</span><a href='https://www.imperva.com/'>imperva</a></body></html>")

    def test_error_15_is_a_hard_deny(self):
        from restock.retailers.blocks import classify
        for status in (403, 200):
            info = classify(status, self.PAGE)
            self.assertIsNotNone(info)
            self.assertEqual((info.vendor, info.kind, info.needs_human), ("Imperva", "denied", False))
            self.assertTrue(info.hard)
            self.assertIn("few hours", info.message("Pokemon Center"))

    def test_hard_deny_pauses_for_hours(self):
        from restock.retailers import base
        from restock.retailers.blocks import classify
        r = base.Retailer.__new__(base.Retailer)
        r.display = "Pokemon Center"
        with self.assertRaises(base.Blocked) as ctx:
            r._raise(classify(403, self.PAGE))
        self.assertGreaterEqual(ctx.exception.retry_after, 6 * 3600)


class StoreToleranceTests(unittest.TestCase):
    def test_each_store_has_its_own_allowance(self):
        from restock.config import Config, KeywordFilter
        from restock.filters import passes, tolerance_pct
        from restock.models import StockResult
        raw = {"settings": {"msrp_tolerance_pct": 5}, "retailers": {"target": {"msrp_tolerance_pct": 20}},
               "product_types": {}}
        cfg = Config(path="x", raw=raw, watchlist=[], searches=[], keywords=KeywordFilter(), price_rules=[], areas=[])
        self.assertEqual(tolerance_pct(cfg, "target"), 20)
        self.assertEqual(tolerance_pct(cfg, "gamestop"), 5)
        etb = "Pokemon TCG Delta Reign Elite Trainer Box"
        ok, _ = passes(StockResult("target", "Target", "1", etb, "u", price=59.99, online=True), cfg)
        self.assertTrue(ok)
        ok, why = passes(StockResult("gamestop", "GameStop", "1", etb, "u", price=59.99, online=True), cfg)
        self.assertFalse(ok)
        self.assertIn("5% over MSRP", why)
