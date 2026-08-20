from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction

from requests_app.models import Product, ProductAlias
from requests_app.utils import normalize_product_text


# Tek başına kullanıldığında birden fazla ürünü ifade edebilecek
# genel kelimeler. Bu ifadeler otomatik alias yapılmayacak.
GENERIC_ALIAS_TERMS = {
    "su",
    "sut",
    "et",
    "un",
    "yag",
    "cay",
    "kola",
    "ayran",
    "peynir",
    "seker",
    "tuz",
    "pirinc",
    "makarna",
    "deterjan",
    "icecek",
    "sebze",
    "meyve",
}


@dataclass(frozen=True)
class AliasLearningResult:
    """
    Alternatif ürün adı kaydetme işleminin sonucunu taşır.
    """

    code: str
    message: str
    alias: ProductAlias | None = None


def learn_product_alias(
    alias_text: str | None,
    product: Product | None,
) -> AliasLearningResult:
    """
    Kullanıcının düzelttiği ürün ifadesini seçilen katalog
    ürününe alternatif ad olarak bağlar.

    İşlem sırasında:
    - Boş ifadeler reddedilir.
    - Çok genel ifadeler reddedilir.
    - Aynı ürün adı tekrar alias yapılmaz.
    - Başka bir ürüne bağlı alias üzerine yazılmaz.
    - Mevcut aynı alias tekrar oluşturulmaz.
    """

    cleaned_alias = str(alias_text or "").strip()
    normalized_alias = normalize_product_text(cleaned_alias)

    if product is None:
        return AliasLearningResult(
            code="NO_PRODUCT",
            message=(
                "Alternatif ad kaydedilemedi çünkü bir katalog "
                "ürünü seçilmedi."
            ),
        )

    if not normalized_alias:
        return AliasLearningResult(
            code="EMPTY",
            message=(
                "Boş bir ürün adı alternatif ad olarak kaydedilemez."
            ),
        )

    if normalized_alias == product.normalized_name:
        return AliasLearningResult(
            code="SAME_AS_PRODUCT",
            message=(
                f"“{cleaned_alias}” zaten ürünün resmî adıdır; "
                "alternatif ad oluşturulmadı."
            ),
        )

    if normalized_alias in GENERIC_ALIAS_TERMS:
        return AliasLearningResult(
            code="TOO_GENERIC",
            message=(
                f"“{cleaned_alias}” ifadesi birden fazla ürünü "
                "temsil edebilecek kadar geneldir. Satır kaydedildi "
                "ancak alternatif ad oluşturulmadı."
            ),
        )

    # Aynı ifade başka bir ürünün resmî adıysa alias olarak kullanma.
    conflicting_product = (
        Product.objects
        .filter(
            normalized_name=normalized_alias,
        )
        .exclude(
            pk=product.pk,
        )
        .first()
    )

    if conflicting_product is not None:
        return AliasLearningResult(
            code="PRODUCT_NAME_CONFLICT",
            message=(
                f"“{cleaned_alias}” ifadesi "
                f"{conflicting_product.sap_item_code} — "
                f"{conflicting_product.item_name} ürününün resmî "
                "adıdır. Alternatif ad oluşturulmadı."
            ),
        )

    # Aynı alias başka bir katalog ürününe bağlıysa üzerine yazma.
    conflicting_alias = (
        ProductAlias.objects
        .select_related("product")
        .filter(
            normalized_alias=normalized_alias,
        )
        .exclude(
            product=product,
        )
        .first()
    )

    if conflicting_alias is not None:
        conflicting_alias_product = conflicting_alias.product

        return AliasLearningResult(
            code="ALIAS_CONFLICT",
            message=(
                f"“{cleaned_alias}” ifadesi zaten "
                f"{conflicting_alias_product.sap_item_code} — "
                f"{conflicting_alias_product.item_name} ürününe "
                "bağlıdır. Mevcut kayıt değiştirilmedi."
            ),
        )

    # Aynı üründe aynı alias daha önce oluşturulmuş olabilir.
    existing_alias = (
        ProductAlias.objects
        .filter(
            product=product,
            normalized_alias=normalized_alias,
        )
        .first()
    )

    if existing_alias is not None:
        fields_to_update: list[str] = []

        if existing_alias.alias_name != cleaned_alias:
            existing_alias.alias_name = cleaned_alias

            fields_to_update.extend(
                [
                    "alias_name",
                    "normalized_alias",
                ]
            )

        if not existing_alias.is_active:
            existing_alias.is_active = True
            fields_to_update.append("is_active")

        if fields_to_update:
            existing_alias.save(
                update_fields=list(
                    dict.fromkeys(fields_to_update)
                )
            )

        return AliasLearningResult(
            code="ALREADY_EXISTS",
            message=(
                f"“{cleaned_alias}” alternatif adı bu ürün için "
                "zaten kayıtlıdır."
            ),
            alias=existing_alias,
        )

    try:
        # İç transaction, olası benzersizlik hatasının dış işlemi
        # bozmaması için savepoint oluşturur.
        with transaction.atomic():
            created_alias = ProductAlias.objects.create(
                product=product,
                alias_name=cleaned_alias,
                is_active=True,
            )

    except IntegrityError:
        return AliasLearningResult(
            code="DATABASE_CONFLICT",
            message=(
                f"“{cleaned_alias}” alternatif adı aynı anda başka "
                "bir işlem tarafından kaydedildi. Katalog kontrol "
                "edilmelidir."
            ),
        )

    return AliasLearningResult(
        code="CREATED",
        message=(
            f"“{cleaned_alias}” ifadesi "
            f"{product.sap_item_code} — {product.item_name} ürünü "
            "için alternatif ad olarak kaydedildi."
        ),
        alias=created_alias,
    )
