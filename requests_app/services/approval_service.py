from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from requests_app.models import (
    PurchaseRequest,
    PurchaseRequestLine,
)
from requests_app.services.product_matching_service import (
    compare_units,
)


@dataclass(frozen=True)
class ApprovalIssue:
    """Formun onaylanmasını engelleyen bir problemi temsil eder."""

    code: str
    message: str
    row_number: int | None = None


class PurchaseRequestApprovalError(ValueError):
    """Form onay koşullarını karşılamadığında oluşur."""

    def __init__(
        self,
        issues: list[ApprovalIssue],
    ):
        self.issues = issues

        super().__init__(
            "Satın alma talep formu onay koşullarını karşılamıyor."
        )


def validate_purchase_request_for_approval(
    purchase_request: PurchaseRequest,
) -> list[ApprovalIssue]:
    """
    Satın alma talep formunun onaya uygunluğunu kontrol eder.
    """

    issues: list[ApprovalIssue] = []

    # -------------------------------------------------
    # FORM ÜST BİLGİLERİ
    # -------------------------------------------------

    if not purchase_request.business_name.strip():
        issues.append(
            ApprovalIssue(
                code="MISSING_BUSINESS_NAME",
                message="İşletme adı boş bırakılamaz.",
            )
        )

    if not purchase_request.authorized_person.strip():
        issues.append(
            ApprovalIssue(
                code="MISSING_AUTHORIZED_PERSON",
                message="Yetkili personel bilgisi boş bırakılamaz.",
            )
        )

    if purchase_request.form_date is None:
        issues.append(
            ApprovalIssue(
                code="MISSING_FORM_DATE",
                message="Form tarihi girilmelidir.",
            )
        )

    # Form numarasını şu an zorunlu tutmuyoruz.
    # Zorunlu olması istenirse aşağıdaki kontrol açılabilir:
    #
    # if not purchase_request.form_number.strip():
    #     issues.append(
    #         ApprovalIssue(
    #             code="MISSING_FORM_NUMBER",
    #             message="Form numarası girilmelidir.",
    #         )
    #     )

    # -------------------------------------------------
    # ÜRÜN SATIRLARI
    # -------------------------------------------------

    lines = list(
        purchase_request.lines
        .select_related("matched_product")
        .order_by("row_number")
    )

    if not lines:
        issues.append(
            ApprovalIssue(
                code="NO_LINES",
                message=(
                    "Formda onaylanabilecek herhangi bir ürün "
                    "satırı bulunmuyor."
                ),
            )
        )

        return issues

    for line in lines:
        row_number = line.row_number
        row_prefix = f"{row_number}. satır"

        if not line.product_name.strip():
            issues.append(
                ApprovalIssue(
                    code="MISSING_PRODUCT_NAME",
                    message=f"{row_prefix}: Ürün adı boş.",
                    row_number=row_number,
                )
            )

        if not line.unit.strip():
            issues.append(
                ApprovalIssue(
                    code="MISSING_UNIT",
                    message=f"{row_prefix}: Birim bilgisi boş.",
                    row_number=row_number,
                )
            )

        # AI okuması veya kullanıcı kontrolü geçerli olmalı.
        if line.status != PurchaseRequestLine.Status.VALID:
            issues.append(
                ApprovalIssue(
                    code="READING_NOT_VALID",
                    message=(
                        f"{row_prefix}: Okuma durumu geçerli değil."
                    ),
                    row_number=row_number,
                )
            )

        if line.matched_product_id is None:
            issues.append(
                ApprovalIssue(
                    code="NO_MATCHED_PRODUCT",
                    message=(
                        f"{row_prefix}: Katalog ürünü seçilmemiş."
                    ),
                    row_number=row_number,
                )
            )

        else:
            if (
                line.matching_status
                != PurchaseRequestLine.MatchingStatus.MATCHED
            ):
                issues.append(
                    ApprovalIssue(
                        code="MATCH_NOT_APPROVED",
                        message=(
                            f"{row_prefix}: Ürün eşleşmesi hâlâ "
                            "kontrol bekliyor."
                        ),
                        row_number=row_number,
                    )
                )

            unit_comparison = compare_units(
                line.unit,
                line.matched_product.unit,
            )

            if unit_comparison is False:
                issues.append(
                    ApprovalIssue(
                        code="UNIT_MISMATCH",
                        message=(
                            f"{row_prefix}: Formdaki birim "
                            f"“{line.unit}”, katalog ürününün "
                            f"birimi “{line.matched_product.unit}” "
                            "ile uyuşmuyor."
                        ),
                        row_number=row_number,
                    )
                )

        quantities = [
            line.week1,
            line.week2,
            line.week3,
            line.week4,
            line.week5,
        ]

        has_positive_quantity = any(
            quantity is not None
            and quantity > Decimal("0")
            for quantity in quantities
        )

        if not has_positive_quantity:
            issues.append(
                ApprovalIssue(
                    code="NO_QUANTITY",
                    message=(
                        f"{row_prefix}: En az bir haftada sıfırdan "
                        "büyük miktar bulunmalıdır."
                    ),
                    row_number=row_number,
                )
            )

    return issues


@transaction.atomic
def approve_purchase_request(
    purchase_request_id: int,
    approved_by,
) -> PurchaseRequest:
    """
    Formu satır kilidi altında tekrar kontrol eder ve onaylar.
    """

    purchase_request = (
        PurchaseRequest.objects
        .select_for_update()
        .get(pk=purchase_request_id)
    )

    if purchase_request.status == PurchaseRequest.Status.APPROVED:
        return purchase_request

    issues = validate_purchase_request_for_approval(
        purchase_request
    )

    if issues:
        raise PurchaseRequestApprovalError(issues)

    purchase_request.status = PurchaseRequest.Status.APPROVED
    purchase_request.approved_at = timezone.now()
    purchase_request.approved_by = approved_by
    purchase_request.error_message = ""

    purchase_request.save(
        update_fields=[
            "status",
            "approved_at",
            "approved_by",
            "error_message",
            "updated_at",
        ]
    )

    return purchase_request
