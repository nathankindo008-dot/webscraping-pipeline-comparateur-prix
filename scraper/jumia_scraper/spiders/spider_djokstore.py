"""
Spider DjokStore.ci — Shopify JSON API
Site e-commerce Côte d'Ivoire (électronique, électroménager, mode)

Utilise l'endpoint Shopify /products.json (autorisé par robots.txt).
Respecte un délai de 2s entre les requêtes.
"""

import json
import scrapy
from datetime import datetime


class DjokStoreSpider(scrapy.Spider):
    name = "djokstore_ci"
    allowed_domains = ["djokstore.ci"]

    BASE_URL = "https://djokstore.ci"
    API_URL = f"{BASE_URL}/products.json"

    PRODUCTS_PER_PAGE = 250
    MAX_PRODUCTS = 200

    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_DELAY": 2,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "USER_AGENT": (
            "ENSEA-Educational-Bot/1.0 "
            "(Projet web scraping comparateur de prix; "
            "contact: nathan.kindo@ensea.edu.ci)"
        ),
        "FEEDS": {
            "raw_data_djokstore.json": {
                "format": "json",
                "encoding": "utf8",
                "overwrite": True,
            }
        },
        "CLOSESPIDER_ITEMCOUNT": 200,
    }

    def start_requests(self):
        yield scrapy.Request(
            url=f"{self.API_URL}?limit={self.PRODUCTS_PER_PAGE}&page=1",
            callback=self.parse,
            meta={"page": 1, "count": 0},
        )

    def parse(self, response):
        page = response.meta["page"]
        count = response.meta["count"]

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            self.logger.error(f"[DjokStore] Page {page} — JSON invalide")
            return

        products = data.get("products", [])
        if not products:
            self.logger.info(f"[DjokStore] Page {page} — plus de produits, fin.")
            return

        self.logger.info(f"[DjokStore] Page {page} — {len(products)} produits")

        for product in products:
            if count >= self.MAX_PRODUCTS:
                self.logger.info(f"[DjokStore] Limite {self.MAX_PRODUCTS} atteinte.")
                return

            item = self._parse_product(product)
            if item:
                count += 1
                yield item

        if count < self.MAX_PRODUCTS and len(products) == self.PRODUCTS_PER_PAGE:
            next_page = page + 1
            yield scrapy.Request(
                url=f"{self.API_URL}?limit={self.PRODUCTS_PER_PAGE}&page={next_page}",
                callback=self.parse,
                meta={"page": next_page, "count": count},
            )

    def _parse_product(self, product):
        try:
            title = (product.get("title") or "").strip()
            if not title:
                return None

            variant = product.get("variants", [{}])[0]
            price_raw = variant.get("price")
            old_price_raw = variant.get("compare_at_price")

            price = int(float(price_raw)) if price_raw else 0
            old_price = int(float(old_price_raw)) if old_price_raw else None

            if price <= 0:
                return None

            discount = None
            if old_price and old_price > price:
                discount = f"-{round((old_price - price) / old_price * 100)}%"

            category = product.get("product_type") or "general"
            category = category.strip().lower().replace(" ", "-") if category else "general"
            if not category:
                category = "general"

            handle = product.get("handle", "")
            product_url = f"{self.BASE_URL}/products/{handle}" if handle else ""

            images = product.get("images", [])
            image_url = images[0].get("src", "") if images else ""

            return {
                "name": title,
                "category": category,
                "price": price,
                "old_price": old_price,
                "discount": discount,
                "currency": "XOF",
                "reviews_count": 0,
                "product_url": product_url,
                "image_url": image_url,
                "page_url": product_url,
                "source": "djokstore_ci",
                "scraped_at": datetime.now().isoformat(),
            }

        except Exception as e:
            self.logger.error(f"[DjokStore] Erreur parsing: {e}")
            return None
