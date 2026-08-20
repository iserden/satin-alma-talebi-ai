import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from django.db import transaction

from requests_app.models import PurchaseRequest, PurchaseRequestLine
from .product_matching_service import (
    match_purchase_request_lines,
)


class AIResultValidationError(ValueError):
    """AI sonucunun beklenen yapıya uymadığını belirtir."""


def load_demo_ai_result() -> dict[str, Any]:
    """Demo AI JSON dosyasını okuyup Python sözlüğü olarak döndürür."""

    file_path = (
        Path(__file__).resolve().parent.parent
        / "demo_data"
        / "sample_ai_result.json"
    )

    try:
        with file_path.open(
            mode="r",
            encoding="utf-8",
        ) as json_file:
            data = json.load(json_file)

    except FileNotFoundError as exc:
        raise AIResultValidationError(
            f"Demo JSON dosyası bulunamadı: {file_path}"
        ) from exc

    except json.JSONDecodeError as exc:
        raise AIResultValidationError(
            (
                "Demo JSON dosyasının biçimi hatalı. "
                f"Satır: {exc.lineno}, sütun: {exc.colno}"
            )
        ) from exc

    return data


def clean_text(
    value: Any,
    maximum_length: int,
) -> str:
    """Metni güvenli biçimde temizler ve uzunluğunu sınırlar."""

    if value is None:
        return ""

    return str(value).strip()[:maximum_length]


def parse_form_date(value: Any):
    """YYYY-AA-GG biçimindeki tarihi Python date nesnesine çevirir."""

    if value in (None, ""):
        return None

    try:
        return datetime.strptime(
            str(value),
            "%Y-%m-%d",
        ).date()

    except ValueError as exc:
        raise AIResultValidationError(
            (
                f"Geçersiz form tarihi: {value}. "
                "Tarih YYYY-AA-GG biçiminde olmalıdır."
            )
        ) from exc


def parse_row_number(value: Any) -> int:
    """Satır numarasının 1-30 arasında tam sayı olduğunu kontrol eder."""

    if isinstance(value, bool):
        raise AIResultValidationError(
            "Satır numarası doğru bir tam sayı olmalıdır."
        )

    try:
        row_number = int(value)

    except (TypeError, ValueError) as exc:
        raise AIResultValidationError(
            f"Geçersiz satır numarası: {value}"
        ) from exc

    if not 1 <= row_number <= 30:
        raise AIResultValidationError(
            f"Satır numarası 1 ile 30 arasında olmalıdır: {row_number}"
        )

    return row_number


def parse_quantity(
    value: Any,
    field_name: str,
) -> Decimal | None:
    """Haftalık miktarı negatif olmayan Decimal değerine dönüştürür."""

    if value in (None, ""):
        return None

    try:
        quantity = Decimal(str(value))

    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AIResultValidationError(
            f"{field_name} alanında geçersiz miktar bulundu: {value}"
        ) from exc

    if quantity < 0:
        raise AIResultValidationError(
            f"{field_name} alanındaki miktar negatif olamaz."
        )

    if quantity >= Decimal("10000000000"):
        raise AIResultValidationError(
            f"{field_name} alanındaki miktar izin verilen sınırı aşıyor."
        )

    return quantity


def parse_confidence(value: Any) -> Decimal | None:
    """Güven skorunu 0 ile 1 arasında Decimal değerine dönüştürür."""

    if value in (None, ""):
        return None

    try:
        confidence = Decimal(str(value))

    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AIResultValidationError(
            f"Geçersiz güven skoru: {value}"
        ) from exc

    if confidence < Decimal("0") or confidence > Decimal("1"):
        raise AIResultValidationError(
            "Güven skoru 0 ile 1 arasında olmalıdır."
        )

    return confidence


def determine_line_status(
    confidence: Decimal | None,
) -> str:
    """Güven skoruna göre sistem içi kontrol durumunu belirler."""

    if confidence is not None and confidence >= Decimal("0.90"):
        return PurchaseRequestLine.Status.VALID

    return PurchaseRequestLine.Status.REVIEW_REQUIRED


def validate_ai_result(
    data: Any,
) -> dict[str, Any]:
    """AI sonucunu kontrol eder ve normalize edilmiş veri döndürür."""

    if not isinstance(data, dict):
        raise AIResultValidationError(
            "AI sonucu bir JSON nesnesi olmalıdır."
        )

    items = data.get("items")

    if not isinstance(items, list):
        raise AIResultValidationError(
            "AI sonucundaki items alanı bir liste olmalıdır."
        )

    if len(items) > 30:
        raise AIResultValidationError(
            "Bir formda en fazla 30 ürün satırı bulunabilir."
        )

    normalized_items: list[dict[str, Any]] = []
    used_row_numbers: set[int] = set()

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise AIResultValidationError(
                f"{index}. ürün satırı bir JSON nesnesi değildir."
            )

        row_number = parse_row_number(
            item.get("row_number")
        )

        if row_number in used_row_numbers:
            raise AIResultValidationError(
                f"{row_number}. satır numarası birden fazla kez kullanılmış."
            )

        used_row_numbers.add(row_number)

        raw_product_name = clean_text(
            item.get("raw_product_name"),
            maximum_length=300,
        )

        product_name = clean_text(
            item.get("product_name"),
            maximum_length=300,
        )

        if not product_name:
            product_name = raw_product_name

        if not product_name:
            raise AIResultValidationError(
                f"{row_number}. satırda ürün adı bulunamadı."
            )

        unit = clean_text(
            item.get("unit"),
            maximum_length=30,
        ).upper()

        if not unit:
            raise AIResultValidationError(
                f"{row_number}. satırda birim bulunamadı."
            )

        confidence = parse_confidence(
            item.get("confidence_score")
        )

        normalized_items.append(
            {
                "row_number": row_number,
                "raw_product_name": raw_product_name,
                "product_name": product_name,
                "unit": unit,
                "week1": parse_quantity(
                    item.get("week1"),
                    f"{row_number}. satır 1. hafta",
                ),
                "week2": parse_quantity(
                    item.get("week2"),
                    f"{row_number}. satır 2. hafta",
                ),
                "week3": parse_quantity(
                    item.get("week3"),
                    f"{row_number}. satır 3. hafta",
                ),
                "week4": parse_quantity(
                    item.get("week4"),
                    f"{row_number}. satır 4. hafta",
                ),
                "week5": parse_quantity(
                    item.get("week5"),
                    f"{row_number}. satır 5. hafta",
                ),
                "confidence_score": confidence,
                "status": determine_line_status(confidence),
            }
        )

    return {
        "business_name": clean_text(
            data.get("business_name"),
            maximum_length=200,
        ),
        "authorized_person": clean_text(
            data.get("authorized_person"),
            maximum_length=200,
        ),
        "form_date": parse_form_date(
            data.get("form_date")
        ),
        "form_number": clean_text(
            data.get("form_number"),
            maximum_length=100,
        ),
        "raw_ocr_text": clean_text(
            data.get("raw_ocr_text"),
            maximum_length=20000,
        ),
        "items": normalized_items,
    }


@transaction.atomic
def apply_ai_result(
    purchase_request: PurchaseRequest,
    data: dict[str, Any],
) -> PurchaseRequest:
    """
    Doğrulanmış AI sonucunu forma ve ürün satırlarına aktarır.

    Mevcut ürün satırları silinerek AI sonucu yeniden oluşturulur.
    """

    normalized_data = validate_ai_result(data)

    purchase_request.business_name = normalized_data["business_name"]
    purchase_request.authorized_person = normalized_data[
        "authorized_person"
    ]
    purchase_request.form_date = normalized_data["form_date"]
    purchase_request.form_number = normalized_data["form_number"]
    purchase_request.raw_ocr_text = normalized_data["raw_ocr_text"]

    # AI'dan gelen orijinal JSON denetim amacıyla saklanır.
    purchase_request.extracted_data = data

    purchase_request.status = (
        PurchaseRequest.Status.REVIEW_REQUIRED
    )

    purchase_request.error_message = ""

    purchase_request.save(
        update_fields=[
            "business_name",
            "authorized_person",
            "form_date",
            "form_number",
            "raw_ocr_text",
            "extracted_data",
            "status",
            "error_message",
            "updated_at",
        ]
    )

    # Demo işlemi yeniden çalıştırılırsa eski satırları tekrar etmeyiz.
    purchase_request.lines.all().delete()

    new_lines = [
        PurchaseRequestLine(
            purchase_request=purchase_request,
            **item,
        )
        for item in normalized_data["items"]
    ]

    PurchaseRequestLine.objects.bulk_create(new_lines)

    match_purchase_request_lines(
    purchase_request=purchase_request,
)

    return purchase_request
