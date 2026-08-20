from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Prefetch
from rapidfuzz import fuzz

from requests_app.models import (
    Product,
    ProductAlias,
    PurchaseRequest,
    PurchaseRequestLine,
)
from requests_app.utils import normalize_product_text


# Benzer metnin otomatik eşleşmesi için gereken alt sınır.
AUTO_MATCH_THRESHOLD = 92.0

# Bu puanın altındaki sonuçlar eşleşmemiş sayılır.
MINIMUM_MATCH_THRESHOLD = 78.0

# İlk iki sonuç birbirine çok yakınsa otomatik seçim yapılmaz.
AMBIGUITY_MARGIN = 4.0


UNIT_ALIASES = {
    "kg": "KG",
    "kilo": "KG",
    "kilogram": "KG",

    "gr": "GR",
    "g": "GR",
    "gram": "GR",

    "lt": "LT",
    "l": "LT",
    "litre": "LT",
    "liter": "LT",

    "ml": "ML",
    "mililitre": "ML",

    "adet": "ADET",
    "ad": "ADET",
    "tane": "ADET",

    "koli": "KOLI",
    "kasa": "KASA",

    "paket": "PAKET",
    "pkt": "PAKET",

    "kutu": "KUTU",

    "rulo": "RULO",

    "demet": "DEMET",

    "cuval": "CUVAL",
    "çuval": "CUVAL",

    "palet": "PALET",
}


@dataclass(frozen=True)
class ProductMatchResult:
    """
    Bir talep satırı için üretilen ürün eşleştirme sonucudur.
    """

    product: Product | None
    confidence: Decimal | None
    status: str
    method: str


def normalize_unit(value: str | None) -> str:
    """
    Birim isimlerini karşılaştırılabilir hâle getirir.

    Örnek:
    koli  → KOLI
    kilo  → KG
    adet  → ADET
    """

    normalized_value = normalize_product_text(value)

    if not normalized_value:
        return ""

    return UNIT_ALIASES.get(
        normalized_value,
        normalized_value.upper(),
    )


def compare_units(
    line_unit: str | None,
    product_unit: str | None,
) -> bool | None:
    """
    Talep satırındaki birim ile katalog ürününün birimini karşılaştırır.

    True:
        Birimler aynı.

    False:
        Birimler farklı.

    None:
        Birimlerden en az biri boş.
    """

    normalized_line_unit = normalize_unit(line_unit)
    normalized_product_unit = normalize_unit(product_unit)

    if not normalized_line_unit or not normalized_product_unit:
        return None

    return normalized_line_unit == normalized_product_unit


def score_to_decimal(score: float) -> Decimal:
    """
    0–100 arasındaki skoru 0–1 arasındaki Decimal değere çevirir.

    Örnek:
    94.5 → 0.9450
    """

    decimal_score = Decimal(str(score)) / Decimal("100")

    return decimal_score.quantize(
        Decimal("0.0001"),
        rounding=ROUND_HALF_UP,
    )


def calculate_text_similarity(
    first_text: str,
    second_text: str,
) -> float:
    """
    İki ürün adı arasındaki benzerlik puanını hesaplar.

    Hem düz karşılaştırma hem de kelime sırası değiştirilmiş
    karşılaştırma yapılır.
    """

    if not first_text or not second_text:
        return 0.0

    ratio_score = fuzz.ratio(
        first_text,
        second_text,
    )

    token_sort_score = fuzz.token_sort_ratio(
        first_text,
        second_text,
    )

    return float(
        max(
            ratio_score,
            token_sort_score,
        )
    )


def get_active_products() -> list[Product]:
    """
    Aktif ürünleri ve aktif alternatif adlarını tek sorgu yapısında getirir.
    """

    active_aliases = ProductAlias.objects.filter(
        is_active=True,
    )

    return list(
        Product.objects.filter(
            is_active=True,
        ).prefetch_related(
            Prefetch(
                "aliases",
                queryset=active_aliases,
            )
        )
    )


def find_exact_candidates(
    normalized_product_name: str,
    products: list[Product],
) -> list[tuple[Product, str]]:
    """
    Resmî ürün adı veya alternatif ad üzerinden birebir eşleşmeleri bulur.
    """

    candidates: dict[int, tuple[Product, str]] = {}

    for product in products:
        if product.normalized_name == normalized_product_name:
            candidates[product.pk] = (
                product,
                PurchaseRequestLine.MatchingMethod.EXACT_NAME,
            )

            continue

        for alias in product.aliases.all():
            if alias.normalized_alias == normalized_product_name:
                candidates[product.pk] = (
                    product,
                    PurchaseRequestLine.MatchingMethod.ALIAS,
                )

                break

    return list(candidates.values())


def select_exact_candidate(
    candidates: list[tuple[Product, str]],
    line_unit: str | None,
) -> ProductMatchResult | None:
    """
    Tam eşleşme sonuçlarından doğru ürünü seçmeye çalışır.
    """

    if not candidates:
        return None

    # Birden fazla tam eşleşme varsa birime göre ayrıştırmaya çalış.
    if len(candidates) > 1:
        same_unit_candidates = [
            candidate
            for candidate in candidates
            if compare_units(
                line_unit,
                candidate[0].unit,
            ) is True
        ]

        if len(same_unit_candidates) == 1:
            candidates = same_unit_candidates

        else:
            return ProductMatchResult(
                product=None,
                confidence=Decimal("0.9000"),
                status=(
                    PurchaseRequestLine
                    .MatchingStatus
                    .REVIEW_REQUIRED
                ),
                method=candidates[0][1],
            )

    product, method = candidates[0]

    unit_result = compare_units(
        line_unit,
        product.unit,
    )

    if unit_result is False:
        return ProductMatchResult(
            product=product,
            confidence=Decimal("0.9500"),
            status=(
                PurchaseRequestLine
                .MatchingStatus
                .REVIEW_REQUIRED
            ),
            method=method,
        )

    return ProductMatchResult(
        product=product,
        confidence=Decimal("1.0000"),
        status=PurchaseRequestLine.MatchingStatus.MATCHED,
        method=method,
    )


def calculate_product_score(
    normalized_product_name: str,
    line_unit: str | None,
    product: Product,
) -> float:
    """
    Talep satırını bir katalog ürünüyle karşılaştırır.

    Ürün adı ve alias değerleri arasından en yüksek puan alınır.
    Birim uyuşması puanı az miktarda yükseltir.
    Birim uyuşmazlığı puanı düşürür.
    """

    scores = [
        calculate_text_similarity(
            normalized_product_name,
            product.normalized_name,
        )
    ]

    for alias in product.aliases.all():
        scores.append(
            calculate_text_similarity(
                normalized_product_name,
                alias.normalized_alias,
            )
        )

    best_score = max(scores)

    unit_result = compare_units(
        line_unit,
        product.unit,
    )

    if unit_result is True:
        best_score += 2.0

    elif unit_result is False:
        best_score -= 8.0

    return max(
        0.0,
        min(best_score, 100.0),
    )


def find_fuzzy_match(
    normalized_product_name: str,
    line_unit: str | None,
    products: list[Product],
) -> ProductMatchResult:
    """
    Tam eşleşme bulunamadığında benzer metin üzerinden ürün arar.
    """

    scored_products: list[tuple[float, Product]] = []

    for product in products:
        score = calculate_product_score(
            normalized_product_name=normalized_product_name,
            line_unit=line_unit,
            product=product,
        )

        scored_products.append(
            (
                score,
                product,
            )
        )

    scored_products.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    if not scored_products:
        return ProductMatchResult(
            product=None,
            confidence=None,
            status=(
                PurchaseRequestLine
                .MatchingStatus
                .NOT_MATCHED
            ),
            method=PurchaseRequestLine.MatchingMethod.NONE,
        )

    top_score, top_product = scored_products[0]

    second_score = (
        scored_products[1][0]
        if len(scored_products) > 1
        else 0.0
    )

    if top_score < MINIMUM_MATCH_THRESHOLD:
        return ProductMatchResult(
            product=None,
            confidence=score_to_decimal(top_score),
            status=(
                PurchaseRequestLine
                .MatchingStatus
                .NOT_MATCHED
            ),
            method=PurchaseRequestLine.MatchingMethod.FUZZY,
        )

    is_ambiguous = (
        second_score > 0
        and top_score - second_score < AMBIGUITY_MARGIN
    )

    unit_result = compare_units(
        line_unit,
        top_product.unit,
    )

    if (
        top_score < AUTO_MATCH_THRESHOLD
        or is_ambiguous
        or unit_result is False
    ):
        return ProductMatchResult(
            product=top_product,
            confidence=score_to_decimal(top_score),
            status=(
                PurchaseRequestLine
                .MatchingStatus
                .REVIEW_REQUIRED
            ),
            method=PurchaseRequestLine.MatchingMethod.FUZZY,
        )

    return ProductMatchResult(
        product=top_product,
        confidence=score_to_decimal(top_score),
        status=PurchaseRequestLine.MatchingStatus.MATCHED,
        method=PurchaseRequestLine.MatchingMethod.FUZZY,
    )


def match_purchase_request_line(
    line: PurchaseRequestLine,
    products: list[Product] | None = None,
    save: bool = True,
) -> ProductMatchResult:
    """
    Tek bir satın alma talep satırını katalogla eşleştirir.
    """

    normalized_product_name = normalize_product_text(
        line.product_name or line.raw_product_name
    )

    if not normalized_product_name:
        result = ProductMatchResult(
            product=None,
            confidence=None,
            status=(
                PurchaseRequestLine
                .MatchingStatus
                .NOT_MATCHED
            ),
            method=PurchaseRequestLine.MatchingMethod.NONE,
        )

    else:
        if products is None:
            products = get_active_products()

        exact_candidates = find_exact_candidates(
            normalized_product_name=normalized_product_name,
            products=products,
        )

        result = select_exact_candidate(
            candidates=exact_candidates,
            line_unit=line.unit,
        )

        if result is None:
            result = find_fuzzy_match(
                normalized_product_name=normalized_product_name,
                line_unit=line.unit,
                products=products,
            )

    if save:
        line.matched_product = result.product
        line.matching_confidence = result.confidence
        line.matching_status = result.status
        line.matching_method = result.method

        line.save(
            update_fields=[
                "matched_product",
                "matching_confidence",
                "matching_status",
                "matching_method",
            ]
        )

    return result


@transaction.atomic
def match_purchase_request_lines(
    purchase_request: PurchaseRequest,
) -> dict[str, int]:
    """
    Bir satın alma formundaki bütün ürün satırlarını eşleştirir.
    """

    products = get_active_products()

    summary = {
        "total": 0,
        "matched": 0,
        "review_required": 0,
        "not_matched": 0,
    }

    lines = purchase_request.lines.all().order_by(
        "row_number"
    )

    for line in lines:
        result = match_purchase_request_line(
            line=line,
            products=products,
            save=True,
        )

        summary["total"] += 1

        if (
            result.status
            == PurchaseRequestLine.MatchingStatus.MATCHED
        ):
            summary["matched"] += 1

        elif (
            result.status
            == PurchaseRequestLine
            .MatchingStatus
            .REVIEW_REQUIRED
        ):
            summary["review_required"] += 1

        else:
            summary["not_matched"] += 1

    return summary