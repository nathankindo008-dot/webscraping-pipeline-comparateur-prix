"""
Spider CoinAfrique.com — Petites annonces Côte d'Ivoire
Site de petites annonces (neuf + occasion) avec HTML server-side rendered.

Catégories scrapées : électronique, téléphones, électroménager, informatique, mode.
Respecte robots.txt (seul /wp-admin/ est bloqué).
"""

import scrapy
from datetime import datetime


class CoinAfriqueSpider(scrapy.Spider):
    name = "coinafrique_ci"
    allowed_domains = ["ci.coinafrique.com"]

    BASE_URL = "https://ci.coinafrique.com"

    CATEGORIES = {
        "telephones-tablettes":     "/categorie/telephones-et-tablettes",
        "tv-electronique":          "/categorie/tv-box-et-video-projecteurs",
        "electromenager":           "/categorie/electromenager",
        "informatique":             "/categorie/ordinateurs",
        "mode":                     "/categorie/mode-et-beaute",
        "maison-bureau":            "/categorie/pour-la-maison",
        "articles-sportifs":        "/categorie/sports-et-loisirs",
    }

    MAX_PER_CATEGORY = 60
    MAX_PAGES = 4

    custom_settings = {
        "ROBOTSTXT_OBEY":                 True,
        "DOWNLOAD_DELAY":                 2.5,
        "RANDOMIZE_DOWNLOAD_DELAY":       True,
        "CONCURRENT_REQUESTS":            1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "USER_AGENT": (
            "ENSEA-Educational-Bot/1.0 "
            "(Projet web scraping comparateur de prix; "
            "contact: nathan.kindo@ensea.edu.ci)"
        ),
        "FEEDS": {
            "raw_data_coinafrique.json": {
                "format":    "json",
                "encoding":  "utf8",
                "overwrite": True,
            }
        },
        "CLOSESPIDER_ITEMCOUNT": 420,
    }

    def start_requests(self):
        for category, path in self.CATEGORIES.items():
            yield scrapy.Request(
                url=f"{self.BASE_URL}{path}",
                callback=self.parse,
                meta={"category": category, "page": 1, "count": 0},
            )

    def parse(self, response):
        category = response.meta["category"]
        page = response.meta["page"]
        count = response.meta["count"]

        self.logger.info(f"[CoinAfrique][{category}] Page {page} — {response.url}")

        cards = response.css("div.col.s6.m4.l3 div.ad__card")
        if not cards:
            self.logger.info(f"[CoinAfrique][{category}] Aucune annonce trouvée, fin.")
            return

        for card in cards:
            if count >= self.MAX_PER_CATEGORY:
                self.logger.info(f"[CoinAfrique][{category}] Limite {self.MAX_PER_CATEGORY} atteinte.")
                return

            item = self._parse_card(card, category)
            if item:
                count += 1
                yield item

        if count < self.MAX_PER_CATEGORY and page < self.MAX_PAGES:
            next_page = page + 1
            yield scrapy.Request(
                url=f"{self.BASE_URL}{self.CATEGORIES[category]}?page={next_page}",
                callback=self.parse,
                meta={"category": category, "page": next_page, "count": count},
            )

    def _parse_card(self, card, category):
        try:
            fav_btn = card.css("span.card-fav")
            name = fav_btn.attrib.get("data-ad-title", "").strip()
            price_str = fav_btn.attrib.get("data-ad-price", "0")

            if not name:
                name = card.css("p.ad__card-description a::text").get(default="").strip()
            if not name:
                name = card.css("a.ad__card-image::attr(title)").get(default="").strip()

            price = self._clean_price(price_str)
            if not name or price == 0:
                return None

            href = card.css("a.ad__card-image::attr(href)").get(default="")
            product_url = f"{self.BASE_URL}{href}" if href else ""

            image_url = card.css("img.ad__card-img::attr(src)").get(default="")

            location = card.css("p.ad__card-location span::text").get(default="").strip()

            return {
                "name":          name,
                "category":      category,
                "price":         price,
                "old_price":     None,
                "discount":      None,
                "currency":      "XOF",
                "reviews_count": 0,
                "product_url":   product_url,
                "image_url":     image_url,
                "page_url":      product_url,
                "source":        "coinafrique_ci",
                "location":      location,
                "scraped_at":    datetime.now().isoformat(),
            }

        except Exception as e:
            self.logger.error(f"[CoinAfrique] Erreur parsing : {e}")
            return None

    def _clean_price(self, text):
        if not text:
            return 0
        cleaned = "".join(filter(str.isdigit, str(text)))
        return int(cleaned) if cleaned else 0
