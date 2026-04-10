import scrapy


class JumiaScraperItem(scrapy.Item):
    name = scrapy.Field()
    category = scrapy.Field()
    price = scrapy.Field()
    old_price = scrapy.Field()
    discount = scrapy.Field()
    currency = scrapy.Field()
    reviews_count = scrapy.Field()
    product_url = scrapy.Field()
    image_url = scrapy.Field()
    page_url = scrapy.Field()
    source = scrapy.Field()
    scraped_at = scrapy.Field()
