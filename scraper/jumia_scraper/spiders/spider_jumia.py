import scrapy
import random
import time
from datetime import datetime


class JumiaSpider(scrapy.Spider):
    name = "jumia_ci"
    allowed_domains = ["www.jumia.ci"]

    # Toutes les catégories Jumia CI
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
        "Articles-sportifs":       "https://www.jumia.ci/sports-loisirs/",
        "Automobile":         "https://www.jumia.ci/automobile-outils/",
        "Livres-films-musique":      "https://www.jumia.ci/livres-papeterie/",
        "instruments-musique":      "https://www.jumia.ci/instruments-musique/",
        "jouets et jeux":             "https://www.jumia.ci/jeux-et-jouets/",
        "animalerie":             "https://www.jumia.ci/animalerie/",
        "jardin-plein-air":       "https://www.jumia.ci/terrasse-jardin-exterieur/",
    }

    # Limite : 50 items max par catégorie → max 500 items total (règle éthique)
    MAX_PER_CATEGORY = 50

    custom_settings = {
        "ROBOTSTXT_OBEY":                  True,
        "DOWNLOAD_DELAY":                  2,
        "RANDOMIZE_DOWNLOAD_DELAY":        True,
        "CONCURRENT_REQUESTS":             1,
        "CONCURRENT_REQUESTS_PER_DOMAIN":  1,
        "USER_AGENT": (
            "ENSEA-Educational-Bot/1.0 "
            "(Projet web scraping; "
            "contact: nathan.kindo@ensea.edu.ci)"
        ),
        "FEEDS": {
            "raw_data.json": {
                "format":   "json",
                "encoding": "utf8",
                "overwrite": True,
            }
        },
        "CLOSESPIDER_ITEMCOUNT": 500,
    }

    def start_requests(self):
        for category, url in self.CATEGORIES.items():
            yield scrapy.Request(
                url=url,
                callback=self.parse,
                meta={
                    "category": category,
                    "page": 1,
                    "count": 0,
                }
            )

    def parse(self, response):
        category = response.meta["category"]
        page     = response.meta["page"]
        count    = response.meta["count"]

        self.logger.info(f"[{category}] Page {page} — {response.url}")

        products = response.css("article.prd")

        if not products:
            self.logger.warning(
                f"[{category}] Aucun produit trouvé. "
                "Le site utilise peut-être du JavaScript."
            )
            return

        for product in products:
            if count >= self.MAX_PER_CATEGORY:
                self.logger.info(f"[{category}] Limite {self.MAX_PER_CATEGORY} atteinte.")
                return

            item = self._parse_product(product, category, response.url)
            if item:
                count += 1
                yield item

        # Pagination
        if count < self.MAX_PER_CATEGORY:
            next_page = response.css(
                "a[aria-label='Page suivante']::attr(href)"
            ).get()
            if next_page:
                time.sleep(random.uniform(1.5, 3.0))
                yield response.follow(
                    next_page,
                    callback=self.parse,
                    meta={
                        "category": category,
                        "page":     page + 1,
                        "count":    count,
                    }
                )

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

            # Ignorer les produits sans nom ou sans prix
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
                "scraped_at":   datetime.now().isoformat(),
            }

        except Exception as e:
            self.logger.error(f"Erreur parsing produit [{category}] : {e}")
            return None

    def _clean_price(self, text):
        if not text:
            return 0
        cleaned = "".join(filter(str.isdigit, str(text)))
        return int(cleaned) if cleaned else 0