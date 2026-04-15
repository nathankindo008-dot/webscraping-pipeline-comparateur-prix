import os
import time
import scrapy
from datetime import datetime
from parsel import Selector
from urllib.parse import urljoin

import requests as http_requests

FLARESOLVERR_URL = os.environ.get("FLARESOLVERR_URL", "http://flaresolverr:8191/v1")


class JumiaSpider(scrapy.Spider):
    name = "jumia_ci"
    allowed_domains = ["www.jumia.ci"]

    CATEGORIES = {
        "telephones-tablettes":   "https://www.jumia.ci/telephone-tablette/",
        "tv-electronique":        "https://www.jumia.ci/electronique/",
        "electromenager":         "https://www.jumia.ci/mlp-electromenager/",
        "informatique":           "https://www.jumia.ci/ordinateurs/",
        "maison-bureau":          "https://www.jumia.ci/maison-cuisine-jardin/",
        "mode":                   "https://www.jumia.ci/fashion-mode/",
        "supermarche":            "https://www.jumia.ci/epicerie/",
        "beaute-hygiene":         "https://www.jumia.ci/beaute-hygiene-sante/",
        "produits-bebes":         "https://www.jumia.ci/bebe-puericulture/",
        "agriculture-elevage":    "https://www.jumia.ci/jardin-plein-air-ferme-ranch/",
        "Articles-sportifs":      "https://www.jumia.ci/sports-loisirs/",
        "Automobile":             "https://www.jumia.ci/automobile-outils/",
        "Livres-films-musique":   "https://www.jumia.ci/livres-papeterie/",
        "instruments-musique":    "https://www.jumia.ci/instruments-musique/",
        "jouets et jeux":         "https://www.jumia.ci/jeux-et-jouets/",
        "animalerie":             "https://www.jumia.ci/animalerie/",
        "jardin-plein-air":       "https://www.jumia.ci/terrasse-jardin-exterieur/",
    }

    MAX_PER_CATEGORY = 50

    # Jumia robots.txt autorise le scraping si le bot est identifié
    # et < 200 req/min. On respecte ces règles manuellement car
    # Cloudflare empêche Scrapy de lire robots.txt directement.
    # URLs interdites: *--* (multi-marques), /mobapi/, /fr/, facettes
    DISALLOWED_PATTERNS = ["--", "/mobapi/", "/fr/"]

    custom_settings = {
        "ROBOTSTXT_OBEY":                  False,
        "DOWNLOAD_DELAY":                  2,
        "RANDOMIZE_DOWNLOAD_DELAY":        True,
        "CONCURRENT_REQUESTS":             1,
        "CONCURRENT_REQUESTS_PER_DOMAIN":  1,
        "USER_AGENT": "ENSEA-Bot/1.0 (+https://ensea.ed.ci; educational project)",
        "FEEDS": {
            "raw_data.json": {
                "format":   "json",
                "encoding": "utf8",
                "overwrite": True,
            }
        },
        "CLOSESPIDER_ITEMCOUNT": 500,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._session_id = None

    def _is_allowed_by_robots(self, url):
        """Manual robots.txt compliance (CF blocks direct access)."""
        for pattern in self.DISALLOWED_PATTERNS:
            if pattern in url:
                return False
        if "?" in url:
            return False
        return True

    def _create_session(self):
        """Create a FlareSolverr session to persist CF cookies."""
        try:
            r = http_requests.post(FLARESOLVERR_URL, json={
                "cmd": "sessions.create",
            }, timeout=30)
            data = r.json()
            if data.get("status") == "ok":
                self._session_id = data.get("session")
                self.logger.info(f"FlareSolverr session created: {self._session_id}")
            else:
                self.logger.error(f"Failed to create session: {data}")
        except Exception as e:
            self.logger.error(f"Session creation failed: {e}")

    def _destroy_session(self):
        if not self._session_id:
            return
        try:
            http_requests.post(FLARESOLVERR_URL, json={
                "cmd": "sessions.destroy",
                "session": self._session_id,
            }, timeout=10)
        except Exception:
            pass

    def _fetch(self, url, retries=1):
        """Fetch a URL through FlareSolverr, reusing session cookies."""
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": 60000,
        }
        if self._session_id:
            payload["session"] = self._session_id

        for attempt in range(retries + 1):
            try:
                r = http_requests.post(FLARESOLVERR_URL, json=payload, timeout=70)
                data = r.json()
                if data.get("status") == "ok":
                    sol = data.get("solution", {})
                    return sol.get("response", ""), sol.get("status", 0)
                msg = data.get("message", "")
                self.logger.warning(f"FlareSolverr attempt {attempt+1}: {msg}")
                if attempt < retries:
                    time.sleep(5)
            except Exception as e:
                self.logger.error(f"FlareSolverr request failed: {e}")
                if attempt < retries:
                    time.sleep(5)
        return None, 0

    def start_requests(self):
        self._create_session()

        total_items = 0
        try:
            for category, url in self.CATEGORIES.items():
                if not self._is_allowed_by_robots(url):
                    self.logger.info(f"[{category}] Skipped (robots.txt)")
                    continue

                self.logger.info(f"[{category}] Fetching: {url}")
                html, status = self._fetch(url, retries=1)

                if html and status == 200:
                    for item in self._parse_page(html, url, category, 1, 0):
                        total_items += 1
                        yield item
                else:
                    self.logger.warning(f"[{category}] Failed (status {status})")

                time.sleep(3)
        finally:
            self._destroy_session()

    def parse(self, response):
        pass

    def _parse_page(self, html, url, category, page, count):
        sel = Selector(text=html)

        self.logger.info(f"[{category}] Page {page} — {url}")

        products = sel.css("article.prd")

        if not products:
            self.logger.warning(f"[{category}] Aucun produit page {page}.")
            return

        self.logger.info(f"[{category}] {len(products)} produits trouvés!")

        for product in products:
            if count >= self.MAX_PER_CATEGORY:
                self.logger.info(f"[{category}] Limite {self.MAX_PER_CATEGORY} atteinte.")
                return

            item = self._parse_product(product, category, url)
            if item:
                count += 1
                yield item

        if count < self.MAX_PER_CATEGORY:
            next_link = sel.css(
                "a[aria-label='Page suivante']::attr(href)"
            ).get()
            if next_link:
                next_url = urljoin(url, next_link)
                if not self._is_allowed_by_robots(next_url):
                    self.logger.info(f"[{category}] Next page skipped (robots.txt)")
                    return
                self.logger.info(f"[{category}] Pagination → {next_url}")
                next_html, status = self._fetch(next_url, retries=1)
                if next_html and status == 200:
                    yield from self._parse_page(next_html, next_url, category, page + 1, count)
                time.sleep(3)

    def _parse_product(self, product, category, page_url):
        try:
            name       = product.css("h3.name::text").get(default="").strip()
            price_text = product.css("div.prc::text").get(default="0")
            old_price  = product.css("div.old::text").get(default=None)
            discount   = product.css("div.bdg._dsct::text").get(default=None)
            reviews    = product.css("div.rev::text").get(default="0")
            prod_url   = product.css("a.core::attr(href)").get(default="")
            image_url  = (
                product.css("img.img::attr(data-src)").get()
                or product.css("img.img::attr(src)").get(default="")
            )

            price     = self._clean_price(price_text)
            old_price = self._clean_price(old_price) if old_price else None
            reviews   = int("".join(filter(str.isdigit, reviews)) or 0)

            if not name or price == 0:
                return None

            return {
                "name":         name,
                "category":     category,
                "price":        price,
                "old_price":    old_price,
                "discount":     discount.strip() if discount else None,
                "currency":     "XOF",
                "reviews_count": reviews,
                "product_url":  f"https://www.jumia.ci{prod_url}",
                "image_url":    image_url,
                "page_url":     page_url,
                "source":       "jumia_ci",
                "scraped_at":   datetime.now().isoformat(),
            }

        except Exception as e:
            self.logger.error(f"Erreur parsing [{category}]: {e}")
            return None

    def _clean_price(self, text):
        if not text:
            return 0
        cleaned = "".join(filter(str.isdigit, str(text)))
        return int(cleaned) if cleaned else 0
