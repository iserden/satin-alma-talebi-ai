from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.conf import settings

from requests_app.models import ConsolidationBatch, ConsolidationLine


def _normalize_date(value: str | date | datetime) -> str:
    """
    Tarih değerini SAP'nin beklediği YYYY-MM-DD biçimine dönüştürür.
    """

    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    return value


def _decimal_to_json_number(value: Decimal) -> int | float:
    """
    Decimal değerini JSON içinde kullanılabilecek sayıya dönüştürür.

    5.00 → 5
    5.50 → 5.5
    """

    if value == value.to_integral_value():
        return int(value)

    return float(value)


def calculate_line_total(line: ConsolidationLine) -> Decimal:
    """
    Birleştirme satırındaki beş haftanın toplam miktarını hesaplar.
    """

    return sum(
        (
            line.week1 or Decimal("0"),
            line.week2 or Decimal("0"),
            line.week3 or Decimal("0"),
            line.week4 or Decimal("0"),
            line.week5 or Decimal("0"),
        ),
        start=Decimal("0"),
    )


def build_document_lines(
    batch: ConsolidationBatch,
) -> list[dict[str, Any]]:
    """
    Birleştirme satırlarını SAP DocumentLines formatına dönüştürür.
    """

    warehouse_code = settings.SAP_SERVICE_LAYER["DEFAULT_WAREHOUSE"]

    consolidation_lines = (
        ConsolidationLine.objects
        .filter(batch=batch)
        .select_related("product")
        .order_by("id")
    )

    document_lines: list[dict[str, Any]] = []

    for line in consolidation_lines:
        product = line.product
        item_code = product.sap_item_code
        total_quantity = calculate_line_total(line)

        if not item_code:
            raise ValueError(
                f"{product.item_name} ürününün SAP kalem kodu bulunmuyor."
            )

        if total_quantity <= 0:
            continue

        document_lines.append(
            {
                "ItemCode": item_code,
                "Quantity": _decimal_to_json_number(total_quantity),
                "WarehouseCode": warehouse_code,
            }
        )

    if not document_lines:
        raise ValueError(
            "SAP'ye gönderilebilecek miktarı bulunan birleştirme satırı yok."
        )

    return document_lines


def build_purchase_request_payload(
    batch: ConsolidationBatch,
    *,
    required_date: str | date | datetime,
) -> dict[str, Any]:
    """
    Bir birleştirme kaydı için SAP satın alma talebi payload'u oluşturur.
    """

    return {
        # SAP Service Layer testinde kabul edilen alan yazımıdır.
        "RequriedDate": _normalize_date(required_date),
        "Comments": (
            f"Django satın alma talebi - "
            f"Birleştirme #{batch.id} - {batch.title}"
        ),
        "DocumentLines": build_document_lines(batch),
    }