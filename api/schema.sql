"""
models.py — SQLAlchemy ORM
Correspondance exacte avec schema.sql
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, Numeric, DateTime,
    ForeignKey, CheckConstraint, UniqueConstraint, func
)
from sqlalchemy.orm import relationship, DeclarativeBase


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    product_url = Column(Text, nullable=False, unique=True)
    name        = Column(Text, nullable=False)
    category    = Column(String(60), nullable=False)
    currency    = Column(String(3), nullable=False, default="XOF")
    image_url   = Column(Text)
    page_url    = Column(Text)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now())

    # Relation 1-N vers price_history
    price_snapshots = relationship(
        "PriceHistory",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="PriceHistory.scraped_at.desc()"
    )

    @property
    def latest_price(self):
        """Retourne le snapshot de prix le plus récent."""
        if self.price_snapshots:
            return self.price_snapshots[0]
        return None

    def __repr__(self):
        return f"<Product id={self.id} category={self.category!r} name={self.name[:40]!r}>"


class PriceHistory(Base):
    __tablename__ = "price_history"

    __table_args__ = (
        CheckConstraint("price > 0",                         name="chk_price_positive"),
        CheckConstraint("old_price IS NULL OR old_price > price",
                                                             name="chk_old_price_coherent"),
        CheckConstraint("discount_pct IS NULL OR (discount_pct >= 0 AND discount_pct <= 100)",
                                                             name="chk_discount_range"),
    )

    id            = Column(Integer, primary_key=True, autoincrement=True)
    product_id    = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    price         = Column(Numeric(12, 0), nullable=False)
    old_price     = Column(Numeric(12, 0), nullable=True)
    discount_pct  = Column(Numeric(5, 2),  nullable=True)
    reviews_count = Column(Integer, nullable=False, default=0)
    scraped_at    = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    # Relation N-1 vers products
    product = relationship("Product", back_populates="price_snapshots")

    def __repr__(self):
        return (f"<PriceHistory product_id={self.product_id} "
                f"price={self.price} scraped_at={self.scraped_at}>")