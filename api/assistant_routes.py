"""
Routes de l'assistant conversationnel.
Flask fournit le contexte produits depuis la DB.
L'appel au LLM (Groq / Llama) est fait côté navigateur pour
contourner les restrictions réseau Docker Desktop / Cloudflare.
"""
import os
import re

from flask import Blueprint, abort, jsonify, render_template, request
from sqlalchemy import func

from extensions import db
from models import Product, PriceHistory

assistant_bp = Blueprint("assistant", __name__)

SYSTEM_PROMPT = """\
Tu es JumiBot, l'assistant du comparateur de prix JumiaPrix CI.
C'est un projet étudiant de l'ENSEA (École Nationale Supérieure de Statistique \
et d'Économie Appliquée, Abidjan, Côte d'Ivoire).

Le site compare les prix de 3 sources ivoiriennes :
- Jumia CI : grande marketplace e-commerce
- DjokStore CI : boutique e-commerce locale
- CoinAfrique CI : petites annonces (neuf + occasion)

Tu as accès à des VRAIES stats de la base de données (prix en XOF / Francs CFA).
Les stats incluent : nombre total de produits, répartition par source, \
prix moyen/min/max par catégorie et par source, promos actives, \
réduction moyenne, top 5 des meilleures promos.

PERSONNALITÉ :
- Sympa, naturel, un peu drôle. Tu parles comme un ami qui s'y connaît en bon plans.
- 1-2 emojis max par message.
- Réponds TOUJOURS en français.
- Tu sais discuter de tout, pas seulement des produits.
- Si on te pose une question personnelle ("ça va ?", "t'es qui ?"), \
  réponds naturellement en restant dans ton rôle de JumiBot.
- Si quelqu'un te taquine ou plaisante, joue le jeu.

FORMAT :
- 1 à 5 phrases. Court et percutant.
- N'invente JAMAIS de données ou de prix.

QUAND DES PRODUITS SONT FOURNIS (liste non vide) :
- Les fiches sont DÉJÀ AFFICHÉES visuellement sous ton message.
- NE LISTE PAS les produits. Commente juste ("Le 3e est à -80% 🔥").

QUAND IL N'Y A PAS DE PRODUITS (liste vide) :
- Discute normalement. Si on pose une question d'analyse, utilise les stats.
- Ex: "prix moyen des smartphones ?" → regarde la catégorie telephones-tablettes.
- Ex: "c'est mieux Jumia ou DjokStore ?" → compare les stats des sources.

CONVERSATION GÉNÉRALE :
- Si le message n'a rien à voir avec les produits, discute normalement.
- Tu peux parler de la Côte d'Ivoire, donner des conseils d'achat, \
  expliquer comment fonctionne le site, etc.
- Si tu ne sais pas, dis-le honnêtement.\
"""


_SOURCE_LABELS = {
    "djokstore_ci": "DjokStore CI",
    "jumia_ci": "Jumia CI",
    "coinafrique_ci": "CoinAfrique CI",
}


def _source_label(src: str) -> str:
    return _SOURCE_LABELS.get(src, src)


def _latest_price_subquery():
    return (
        db.session.query(
            PriceHistory.product_id,
            func.max(PriceHistory.scraped_at).label("max_scraped_at"),
        )
        .group_by(PriceHistory.product_id)
        .subquery()
    )


def _get_db_stats() -> dict:
    """Résumé analytique complet de la base pour l'IA."""
    try:
        sub = _latest_price_subquery()
        total_products = db.session.query(func.count(Product.id)).scalar() or 0

        source_counts = (
            db.session.query(Product.source, func.count(Product.id))
            .group_by(Product.source)
            .all()
        )

        price_global = (
            db.session.query(
                func.min(PriceHistory.price),
                func.max(PriceHistory.price),
                func.avg(PriceHistory.price),
            )
            .join(sub, (PriceHistory.product_id == sub.c.product_id)
                  & (PriceHistory.scraped_at == sub.c.max_scraped_at))
            .first()
        )

        promos_count = (
            db.session.query(func.count(PriceHistory.id))
            .join(sub, (PriceHistory.product_id == sub.c.product_id)
                  & (PriceHistory.scraped_at == sub.c.max_scraped_at))
            .filter(PriceHistory.discount_pct.isnot(None), PriceHistory.discount_pct > 0)
            .scalar()
        ) or 0

        avg_discount = (
            db.session.query(func.avg(PriceHistory.discount_pct))
            .join(sub, (PriceHistory.product_id == sub.c.product_id)
                  & (PriceHistory.scraped_at == sub.c.max_scraped_at))
            .filter(PriceHistory.discount_pct.isnot(None), PriceHistory.discount_pct > 0)
            .scalar()
        )

        cat_stats = (
            db.session.query(
                Product.category,
                func.count(Product.id),
                func.min(PriceHistory.price),
                func.max(PriceHistory.price),
                func.avg(PriceHistory.price),
            )
            .join(sub, Product.id == sub.c.product_id)
            .join(PriceHistory,
                  (PriceHistory.product_id == sub.c.product_id)
                  & (PriceHistory.scraped_at == sub.c.max_scraped_at))
            .group_by(Product.category)
            .order_by(func.count(Product.id).desc())
            .all()
        )

        categories = {}
        for cat, nb, pmin, pmax, pavg in cat_stats:
            categories[cat] = {
                "nb_produits": nb,
                "prix_min": int(pmin) if pmin else 0,
                "prix_max": int(pmax) if pmax else 0,
                "prix_moyen": int(pavg) if pavg else 0,
            }

        source_price_stats = (
            db.session.query(
                Product.source,
                func.avg(PriceHistory.price),
                func.min(PriceHistory.price),
                func.max(PriceHistory.price),
            )
            .join(sub, Product.id == sub.c.product_id)
            .join(PriceHistory,
                  (PriceHistory.product_id == sub.c.product_id)
                  & (PriceHistory.scraped_at == sub.c.max_scraped_at))
            .group_by(Product.source)
            .all()
        )

        sources = {}
        for src, avg_p, min_p, max_p in source_price_stats:
            label = _source_label(src)
            sources[label] = {
                "nb_produits": dict(source_counts).get(src, 0),
                "prix_moyen": int(avg_p) if avg_p else 0,
                "prix_min": int(min_p) if min_p else 0,
                "prix_max": int(max_p) if max_p else 0,
            }

        top_promos = (
            db.session.query(Product.name, PriceHistory.price,
                             PriceHistory.old_price, PriceHistory.discount_pct,
                             Product.source, Product.category)
            .join(sub, Product.id == sub.c.product_id)
            .join(PriceHistory,
                  (PriceHistory.product_id == sub.c.product_id)
                  & (PriceHistory.scraped_at == sub.c.max_scraped_at))
            .filter(PriceHistory.discount_pct.isnot(None), PriceHistory.discount_pct > 0)
            .order_by(PriceHistory.discount_pct.desc())
            .limit(5)
            .all()
        )
        best_deals = []
        for name, price, old_p, disc, src, cat in top_promos:
            best_deals.append({
                "nom": name,
                "prix": int(price),
                "ancien_prix": int(old_p) if old_p else None,
                "reduction": f"-{int(disc)}%",
                "source": _source_label(src),
                "categorie": cat,
            })

        return {
            "total_produits": total_products,
            "sources": sources,
            "categories": categories,
            "prix_global": {
                "min_xof": int(price_global[0]) if price_global[0] else 0,
                "max_xof": int(price_global[1]) if price_global[1] else 0,
                "moyen_xof": int(price_global[2]) if price_global[2] else 0,
            },
            "promos": {
                "nb_actives": promos_count,
                "reduction_moyenne": f"{avg_discount:.0f}%" if avg_discount else "0%",
                "top_5_meilleures": best_deals,
            },
        }
    except Exception:
        return {"total_produits": 0, "erreur": "stats indisponibles"}


def _extract_chat_filters(message: str) -> dict:
    msg = message.lower()
    filters = {"source": None, "max_price": None, "category": None, "query": None}

    if "djok" in msg:
        filters["source"] = "djokstore_ci"
    elif "jumia" in msg:
        filters["source"] = "jumia_ci"
    elif "coin" in msg or "coinafrique" in msg:
        filters["source"] = "coinafrique_ci"

    match_price = re.search(r"(?:moins de|inferieur a|max|budget|<)\s*([\d\s]+)", msg)
    if match_price:
        filters["max_price"] = int(re.sub(r"\s+", "", match_price.group(1)))

    category_map = {
        "telephone": "telephones-tablettes",
        "smartphone": "telephones-tablettes",
        "tablette": "telephones-tablettes",
        "portable": "telephones-tablettes",
        "iphone": "telephones-tablettes",
        "samsung": "telephones-tablettes",
        "tv": "tv-electronique",
        "televiseur": "tv-electronique",
        "tele": "tv-electronique",
        "electronique": "tv-electronique",
        "electromenager": "electromenager",
        "frigo": "electromenager",
        "climatiseur": "electromenager",
        "ventilo": "electromenager",
        "lave-linge": "electromenager",
        "micro-onde": "electromenager",
        "informatique": "informatique",
        "laptop": "informatique",
        "ordinateur": "informatique",
        "pc": "informatique",
        "beaute": "beaute-hygiene",
        "parfum": "beaute-hygiene",
        "hygiene": "beaute-hygiene",
        "mode": "mode",
        "vetement": "mode",
        "chaussure": "mode",
        "maison": "maison-bureau",
        "meuble": "maison-bureau",
        "bureau": "maison-bureau",
        "cuisine": "maison-bureau",
        "bebe": "produits-bebes",
        "puericulture": "produits-bebes",
        "sport": "articles-sportifs",
        "fitness": "articles-sportifs",
        "loisir": "articles-sportifs",
        "automobile": "automobile",
        "voiture": "automobile",
        "livre": "livres-films-musique",
        "musique": "instruments-musique",
        "guitare": "instruments-musique",
        "jouet": "jouets-et-jeux",
        "jeu": "jouets-et-jeux",
        "supermarche": "supermarche",
        "epicerie": "supermarche",
        "alimentation": "supermarche",
        "animal": "animalerie",
        "jardin": "jardin-plein-air",
        "agriculture": "agriculture-elevage",
        "drone": "drone",
        "enceinte": "enceinte-bluetooth",
        "bluetooth": "enceinte-bluetooth",
        "onduleur": "onduleur-/-ups",
        "ups": "onduleur-/-ups",
        "peripherique": "périphériques-informatiques",
        "clavier": "périphériques-informatiques",
        "souris": "périphériques-informatiques",
        "ventilateur": "ventillateur",
    }
    for keyword, category in category_map.items():
        if keyword in msg:
            filters["category"] = category
            break

    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", msg)
    tokens = [t for t in cleaned.split() if len(t) >= 3]
    stopwords = {
        "moins", "avec", "pour", "dans", "sur", "des", "les", "une", "un", "bonjour",
        "salut", "bonsoir", "donne", "moi", "conseille", "conseil", "cherche", "prix",
        "xof", "franc", "francs", "assistant", "stp", "svp", "s il", "te", "plait",
        "djokstore", "jumia", "coinafrique", "quel", "quelle", "quels", "est", "meilleur", "meilleure",
        "bon", "bonne", "produit", "produits", "montre", "trouve", "veux", "budget",
        "max", "maximum", "compare", "comparaison",
    }
    if filters.get("category"):
        stopwords.update(category_map.keys())
    if filters.get("source"):
        stopwords.update({"djok", "coin", "coinafrique"})
    cat_keys = set(category_map.keys())
    candidates = [
        t for t in tokens
        if t not in stopwords
        and not t.isdigit()
        and not any(t.startswith(k) or k.startswith(t) for k in cat_keys if filters.get("category"))
    ]
    if candidates:
        filters["query"] = candidates[0]

    return filters


def _search_products_for_chat(filters: dict, limit: int = 8) -> list[dict]:
    sub = _latest_price_subquery()
    base_query = (
        db.session.query(Product, PriceHistory)
        .join(sub, Product.id == sub.c.product_id)
        .join(
            PriceHistory,
            (PriceHistory.product_id == sub.c.product_id)
            & (PriceHistory.scraped_at == sub.c.max_scraped_at),
        )
    )

    if filters.get("source"):
        base_query = base_query.filter(Product.source == filters["source"])
    if filters.get("category"):
        base_query = base_query.filter(Product.category == filters["category"])
    if filters.get("max_price"):
        base_query = base_query.filter(PriceHistory.price <= filters["max_price"])

    query = base_query
    if filters.get("query"):
        query = query.filter(Product.name.ilike(f"%{filters['query'][:40]}%"))

    results = query.order_by(PriceHistory.price.asc()).limit(limit).all()
    if not results and filters.get("query"):
        results = base_query.order_by(PriceHistory.price.asc()).limit(limit).all()

    data = []
    for p, ph in results:
        source_label = _source_label(p.source)
        item = {
            "id": p.id,
            "name": p.name,
            "price": int(ph.price),
            "category": p.category,
            "source": p.source,
            "source_label": source_label,
            "product_url": p.product_url,
            "image_url": p.image_url or "",
            "reviews_count": ph.reviews_count or 0,
        }
        if ph.old_price:
            item["old_price"] = int(ph.old_price)
        if ph.discount_pct:
            item["discount_pct"] = float(ph.discount_pct)
        data.append(item)
    return data


_GREETINGS = {"bonjour", "salut", "bonsoir", "hello", "cc", "coucou", "hey", "hi", "yo",
              "bjr", "slt", "bsr", "wesh", "kikou"}

_FAREWELLS = {"au revoir", "bye", "a+", "a plus", "bonne nuit", "ciao", "tchao",
              "adieu", "bonne soiree", "bonne journee"}

_THANKS = {"merci", "thanks", "merci beaucoup", "thx", "mrc", "cool merci", "ok merci"}

_HOW_ARE_YOU = {"ca va", "ça va", "comment tu vas", "comment ca va", "comment vas-tu",
                "la forme", "tu vas bien", "cv"}

_WHO_ARE_YOU = {"tu es qui", "t'es qui", "c'est qui", "qui es tu", "c quoi",
                "c'est quoi", "tu fais quoi", "tu sers a quoi", "tu sais faire quoi",
                "comment tu marches", "comment ca marche"}

_HELP = {"aide", "help", "comment utiliser", "comment faire", "aide moi",
         "j'ai besoin d'aide", "je comprends pas"}

_PRODUCT_SIGNALS = {
    "cherche", "trouve", "montre", "donne", "propose", "conseil",
    "smartphone", "telephone", "tablette", "iphone", "samsung", "portable",
    "tv", "televiseur", "tele", "ecran",
    "laptop", "ordinateur", "pc", "informatique",
    "frigo", "climatiseur", "ventilateur", "electromenager",
    "beaute", "parfum", "creme",
    "mode", "vetement", "chaussure",
    "jumia", "djokstore", "djok", "coinafrique", "coin",
    "promo", "promotion", "reduction", "solde",
    "budget", "moins", "inferieur", "max", "pas cher",
    "compare", "comparaison", "difference",
    "meilleur", "meilleure", "top", "mieux",
    "produit", "produits", "article", "articles",
    "acheter", "achat", "commander",
    "maison", "meuble", "cuisine", "jardin",
    "bebe", "jouet", "sport", "livre", "musique",
    "supermarche", "epicerie", "automobile", "voiture",
}


def _wants_products(message: str) -> bool:
    """Retourne True si le message ressemble à une demande de produits."""
    msg = message.strip().lower()
    if msg in _GREETINGS:
        return False
    tokens = set(re.sub(r"[^a-zA-Z0-9àâéèêëïîôùûüç\s]", " ", msg).split())
    if tokens & _PRODUCT_SIGNALS:
        return True
    if re.search(r"\d{3,}", msg):
        return True
    return False


def _build_local_chat_response(message: str, db_stats: dict | None = None) -> str:
    msg = message.strip().lower()
    msg_clean = re.sub(r"[^a-zàâéèêëïîôùûüç0-9\s]", " ", msg)
    msg_clean = re.sub(r"\s+", " ", msg_clean).strip()

    if msg_clean in _GREETINGS or msg in _GREETINGS:
        return (
            "Bonjour 👋 Je suis JumiBot, ton assistant shopping ! "
            "Demande-moi des produits, compare les prix, ou discute avec moi."
        )

    if msg_clean in _FAREWELLS or msg in _FAREWELLS:
        return "À bientôt ! 👋 N'hésite pas à revenir si tu cherches un bon plan."

    if msg_clean in _THANKS or msg in _THANKS:
        return "Avec plaisir ! Si tu as besoin d'autre chose, je suis là 😊"

    if any(p in msg_clean for p in _HOW_ARE_YOU):
        return (
            "Ça va super, merci de demander ! 😄 Et toi ? "
            "Si tu cherches un bon plan, je suis prêt."
        )

    if any(p in msg_clean for p in _WHO_ARE_YOU):
        return (
            "Je suis JumiBot, l'assistant du comparateur JumiaPrix CI ! "
            "Je compare les prix entre Jumia, DjokStore et CoinAfrique en Côte d'Ivoire. "
            "Demande-moi un produit, un budget, ou juste discute avec moi 😊"
        )

    if any(p in msg_clean for p in _HELP):
        return (
            "Voilà ce que je sais faire :\n"
            "• Chercher un produit : \"smartphones moins de 100000\"\n"
            "• Filtrer par source : \"produits jumia\" ou \"sur coinafrique\"\n"
            "• Comparer : \"c'est mieux Jumia ou DjokStore ?\"\n"
            "• Analyser : \"prix moyen des TV ?\" ou \"meilleures promos\"\n"
            "Essaie, tu vas voir 😉"
        )

    if db_stats and any(w in msg_clean for w in ("combien", "statistique", "stat", "nombre", "total")):
        total = db_stats.get("total_produits", 0)
        sources = db_stats.get("sources", {})
        parts = [f"{total} produits au total :"]
        for src, info in sources.items():
            parts.append(f"  • {src} : {info['nb_produits']} produits")
        nb_cats = len(db_stats.get("categories", {}))
        parts.append(f"Répartis dans {nb_cats} catégories.")
        promos = db_stats.get("promos", {})
        if promos.get("nb_actives"):
            parts.append(f"{promos['nb_actives']} promos actives (réduction moy. {promos['reduction_moyenne']}) 🔥")
        return "\n".join(parts)

    return ""


@assistant_bp.route("/assistant", methods=["GET"])
def page_assistant():
    return render_template("assistant.html", active_page="assistant")


@assistant_bp.route("/chat/config", methods=["GET"])
def chat_config():
    """
    Configuration Groq pour l'appel LLM côté navigateur.
    ---
    tags: [Assistant]
    responses:
      200:
        description: Config IA (Groq + Llama)
    """
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    return jsonify({
        "enabled": bool(api_key),
        "provider": "groq",
        "api_key": api_key,
        "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "system_prompt": SYSTEM_PROMPT,
        "timeout": int(os.getenv("GROQ_TIMEOUT", "30")),
    }), 200


@assistant_bp.route("/chat", methods=["POST"])
def chat():
    """
    Recherche le contexte produits et retourne une réponse locale +
    stats DB et contexte riche pour l'appel Groq côté navigateur.
    ---
    tags: [Assistant]
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [message]
          properties:
            message: {type: string}
    responses:
      200:
        description: Contexte produits + réponse locale
    """
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        abort(400, description="message requis.")

    wants_products = _wants_products(message)
    products_context = []
    results = []

    if wants_products:
        filters = _extract_chat_filters(message)
        products_context = _search_products_for_chat(filters, limit=10)
        results = products_context[:5]

    db_stats = _get_db_stats()
    local_reply = _build_local_chat_response(message, db_stats)

    return jsonify({
        "reply": local_reply,
        "results": results,
        "context": products_context,
        "db_stats": db_stats,
        "mode": "local",
        "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    }), 200


def register_assistant_routes(app):
    app.register_blueprint(assistant_bp)
