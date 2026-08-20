from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Prefetch

from requests_app.models import (
    ConsolidationBatch,
    ConsolidationLine,
    ConsolidationSource,
    PurchaseRequest,
    PurchaseRequestLine,
)


ZERO = Decimal("0")


class ConsolidationError(ValueError):
    """Talep birleştirme işlemi yapılamadığında oluşur."""


def quantity_or_zero(value) -> Decimal:
    """Boş miktarları toplama işlemi için sıfıra dönüştürür."""

    if value is None:
        return ZERO

    return value


@transaction.atomic
def create_consolidation_batch(
    title: str,
    purchase_request_ids: list[int],
    created_by,
) -> ConsolidationBatch:
    """
    Seçilen onaylı formları SAP katalog ürününe göre birleştirir.
    """

    cleaned_title = str(title or "").strip()

    if not cleaned_title:
        raise ConsolidationError(
            "Birleştirme adı boş bırakılamaz."
        )

    unique_request_ids = list(
        dict.fromkeys(purchase_request_ids)
    )

    if not unique_request_ids:
        raise ConsolidationError(
            "Birleştirme için en az bir talep formu seçilmelidir."
        )

    line_queryset = (
        PurchaseRequestLine.objects
        .select_related("matched_product")
        .order_by("row_number")
    )

    purchase_requests = list(
        PurchaseRequest.objects
        .select_for_update()
        .filter(pk__in=unique_request_ids)
        .prefetch_related(
            Prefetch(
                "lines",
                queryset=line_queryset,
            )
        )
    )

    if len(purchase_requests) != len(unique_request_ids):
        raise ConsolidationError(
            "Seçilen talep formlarından en az biri bulunamadı."
        )

    not_approved_requests = [
        purchase_request.pk
        for purchase_request in purchase_requests
        if (
            purchase_request.status
            != PurchaseRequest.Status.APPROVED
        )
    ]

    if not_approved_requests:
        request_numbers = ", ".join(
            f"#{request_id}"
            for request_id in not_approved_requests
        )

        raise ConsolidationError(
            "Yalnızca onaylanmış formlar birleştirilebilir. "
            f"Onaylı olmayan kayıtlar: {request_numbers}"
        )

    already_used_request_ids = list(
        ConsolidationSource.objects
        .filter(
            purchase_request_id__in=unique_request_ids,
        )
        .values_list(
            "purchase_request_id",
            flat=True,
        )
    )

    if already_used_request_ids:
        request_numbers = ", ".join(
            f"#{request_id}"
            for request_id in already_used_request_ids
        )

        raise ConsolidationError(
            "Bazı formlar daha önce başka bir birleştirmede "
            f"kullanılmış: {request_numbers}"
        )

    product_totals: dict[int, dict] = {}

    for purchase_request in purchase_requests:
        for line in purchase_request.lines.all():
            if line.matched_product_id is None:
                raise ConsolidationError(
                    f"Talep #{purchase_request.pk}, "
                    f"{line.row_number}. satırda katalog ürünü yok."
                )

            if (
                line.matching_status
                != PurchaseRequestLine.MatchingStatus.MATCHED
            ):
                raise ConsolidationError(
                    f"Talep #{purchase_request.pk}, "
                    f"{line.row_number}. satırdaki ürün eşleşmesi "
                    "onaylanmamış."
                )

            product_id = line.matched_product_id

            if product_id not in product_totals:
                product_totals[product_id] = {
                    "product": line.matched_product,
                    "unit": (
                        line.matched_product.unit
                        or line.unit
                    ),
                    "week1": ZERO,
                    "week2": ZERO,
                    "week3": ZERO,
                    "week4": ZERO,
                    "week5": ZERO,
                    "source_request_ids": set(),
                    "source_line_count": 0,
                }

            total_record = product_totals[product_id]

            total_record["week1"] += quantity_or_zero(
                line.week1
            )
            total_record["week2"] += quantity_or_zero(
                line.week2
            )
            total_record["week3"] += quantity_or_zero(
                line.week3
            )
            total_record["week4"] += quantity_or_zero(
                line.week4
            )
            total_record["week5"] += quantity_or_zero(
                line.week5
            )

            total_record["source_request_ids"].add(
                purchase_request.pk
            )

            total_record["source_line_count"] += 1

    if not product_totals:
        raise ConsolidationError(
            "Seçilen formlarda birleştirilebilecek ürün bulunamadı."
        )

    batch = ConsolidationBatch.objects.create(
        title=cleaned_title,
        status=ConsolidationBatch.Status.READY,
        created_by=created_by,
    )

    ConsolidationSource.objects.bulk_create(
        [
            ConsolidationSource(
                batch=batch,
                purchase_request=purchase_request,
            )
            for purchase_request in purchase_requests
        ]
    )

    ConsolidationLine.objects.bulk_create(
        [
            ConsolidationLine(
                batch=batch,
                product=record["product"],
                unit=record["unit"],
                week1=record["week1"],
                week2=record["week2"],
                week3=record["week3"],
                week4=record["week4"],
                week5=record["week5"],
                source_request_count=len(
                    record["source_request_ids"]
                ),
                source_line_count=record[
                    "source_line_count"
                ],
            )
            for record in product_totals.values()
        ]
    )

    return batch
