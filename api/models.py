"""
models.py — SQLAlchemy ORM
Tables : users, products, price_history, user_favorites, price_alerts, user_preferences
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, Numeric, DateTime, Boolean, JSON,
    ForeignKey, CheckConstraint, UniqueConstraint, func
)
from sqlalchemy.orm import relationship, DeclarativeBase


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    username      = Column(String(60), nullable=False, unique=True, index=True)
    email         = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    name          = Column(String(120), nullable=False)
    is_active     = Column(Boolean, default=True)
    is_admin      = Column(Boolean, nullable=False, default=False)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    favorites = relationship("UserFavorite", back_populates="user", cascade="all, delete-orphan")
    alerts    = relationship("PriceAlert", back_populates="user", cascade="all, delete-orphan")
    preference = relationship(
        "UserPreference",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<User id={self.id} email={self.email!r}>"


class UserPreference(Base):
    """Préférences pour recommandations « Pour vous » (questionnaire optionnel)."""
    __tablename__ = "user_preferences"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    user_id      = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    categories   = Column(JSON, nullable=False)
    budget_min   = Column(Integer, nullable=True)
    budget_max   = Column(Integer, nullable=True)
    sources      = Column(JSON, nullable=True)
    updated_at   = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="preference")

    def __repr__(self):
        return f"<UserPreference user_id={self.user_id}>"


class UserFavorite(Base):
    __tablename__ = "user_favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_user_product_fav"),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user    = relationship("User", back_populates="favorites")
    product = relationship("Product")


class PriceAlert(Base):
    __tablename__ = "price_alerts"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    user_id      = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id   = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    target_price = Column(Numeric(12, 0), nullable=False)
    is_active    = Column(Boolean, default=True)
    triggered_at = Column(DateTime(timezone=True), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    user    = relationship("User", back_populates="alerts")
    product = relationship("Product")

    def __repr__(self):
        return f"<PriceAlert user={self.user_id} product={self.product_id} target={self.target_price}>"


# ─────────────────────────────────────────────
# Products
# ─────────────────────────────────────────────
class Product(Base):
    __tablename__ = "products"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    product_url = Column(Text, nullable=False, unique=True)
    name        = Column(Text, nullable=False)
    category    = Column(String(60), nullable=False)
    source      = Column(String(30), nullable=False, default="jumia_ci")
    currency    = Column(String(3), nullable=False, default="XOF")
    image_url   = Column(Text)
    page_url    = Column(Text)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now())

    price_snapshots = relationship(
        "PriceHistory",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="PriceHistory.scraped_at.desc()"
    )

    @property
    def latest_price(self):
        if self.price_snapshots:
            return self.price_snapshots[0]
        return None

    def __repr__(self):
        return f"<Product id={self.id} source={self.source!r} name={self.name[:40]!r}>"


# ─────────────────────────────────────────────
# Product Matches (cross-source)
# ─────────────────────────────────────────────
class ProductMatch(Base):
    __tablename__ = "product_matches"
    __table_args__ = (
        UniqueConstraint("product_id_a", "product_id_b", name="uq_match_pair"),
        CheckConstraint("product_id_a <> product_id_b", name="chk_diff_products"),
    )

    id           = Column(Integer, primary_key=True, autoincrement=True)
    product_id_a = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id_b = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    similarity   = Column(Numeric(5, 2), nullable=False, default=0)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    product_a = relationship("Product", foreign_keys=[product_id_a])
    product_b = relationship("Product", foreign_keys=[product_id_b])


# ─────────────────────────────────────────────
# Price History
# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# Scrape Logs
# ─────────────────────────────────────────────
class ScrapeLog(Base):
    __tablename__ = "scrape_logs"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    source      = Column(String(30), nullable=False)
    status      = Column(String(20), nullable=False, default="running")
    items_raw   = Column(Integer, default=0)
    items_clean = Column(Integer, default=0)
    items_new   = Column(Integer, default=0)
    items_updated = Column(Integer, default=0)
    duration_sec  = Column(Numeric(8, 1), nullable=True)
    error_msg     = Column(Text, nullable=True)
    started_at    = Column(DateTime(timezone=True), server_default=func.now())
    finished_at   = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<ScrapeLog id={self.id} source={self.source!r} status={self.status!r}>"


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

    product = relationship("Product", back_populates="price_snapshots")

    def __repr__(self):
        return (f"<PriceHistory product_id={self.product_id} "
                f"price={self.price} scraped_at={self.scraped_at}>")