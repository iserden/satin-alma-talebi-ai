from __future__ import annotations

from datetime import date, datetime
from typing import Any

import requests
from django.db import transaction
from django.utils import timezone

from requests_app.models import ConsolidationBatch

from .sap_purchase_request_builder import (
    build_purchase_request_payload,
)
from .sap_service_layer_client import (
    SapServiceLayerError,
    get_sap_client,
)


class SapPurchaseRequestSendError(Exception):
    """
    Birleştirme kaydının SAP'ye gönderilmesi sırasında
    oluşan uygulama hatalarını temsil eder.
    """


def _format_service_layer_error(
    exception: Exception,
) -> str:
    """
    SAP veya bağlantı hatasını veritabanında saklanabilecek
    okunabilir bir metne dönüştürür.
    """

    message = str(exception)

    status_code = getattr(
        exception,
        "status_code",
        None,
    )

    sap_error_code = getattr(
        exception,
        "sap_error_code",
        None,
    )

    details = []

    if status_code is not None:
        details.append(
            f"HTTP {status_code}"
        )

    if sap_error_code is not None:
        details.append(
            f"SAP kodu: {sap_error_code}"
        )

    if details:
        return (
            f"{' | '.join(details)} | {message}"
        )

    return message


def send_consolidation_batch_to_sap(
    *,
    batch_id: int,
    required_date: str | date | datetime,
) -> dict[str, Any]:
    """
    Bir birleştirme kaydını SAP Business One üzerinde
    satın alma talebi olarak oluşturur.

    Başarılı işlemde SAP DocEntry ve DocNum bilgilerini döndürür.
    """

    client = get_sap_client()

    send_error: SapPurchaseRequestSendError | None = None
    send_result: dict[str, Any] | None = None

    with transaction.atomic():
        batch = (
            ConsolidationBatch.objects
            .select_for_update()
            .get(pk=batch_id)
        )

        if (
            batch.status
            == ConsolidationBatch.Status.SENT_TO_SAP
            or batch.sap_doc_entry is not None
            or batch.sap_doc_num is not None
        ):
            raise SapPurchaseRequestSendError(
                (
                    "Bu birleştirme daha önce SAP sistemine "
                    "gönderilmiş. Aynı kayıt tekrar gönderilemez."
                )
            )

        payload = build_purchase_request_payload(
            batch,
            required_date=required_date,
        )

        batch.sap_request_payload = payload
        batch.sap_response_data = {}
        batch.sap_error_message = ""

        batch.save(
            update_fields=[
                "sap_request_payload",
                "sap_response_data",
                "sap_error_message",
                "updated_at",
            ]
        )

        try:
            response_data = client.create_purchase_request(
                required_date=payload["RequriedDate"],
                document_lines=payload["DocumentLines"],
                comments=payload.get(
                    "Comments",
                    "",
                ),
            )

        except (
            SapServiceLayerError,
            requests.RequestException,
        ) as exc:
            error_message = _format_service_layer_error(
                exc
            )

            batch.sap_error_message = error_message
            batch.sap_response_data = {}

            batch.save(
                update_fields=[
                    "sap_error_message",
                    "sap_response_data",
                    "updated_at",
                ]
            )

            send_error = SapPurchaseRequestSendError(
                error_message
            )

        else:
            doc_entry = response_data.get(
                "DocEntry"
            )
            doc_num = response_data.get(
                "DocNum"
            )

            if doc_entry is None or doc_num is None:
                error_message = (
                    "SAP başarılı bir cevap döndürdü ancak "
                    "cevap içinde DocEntry veya DocNum bulunamadı."
                )

                batch.sap_error_message = error_message
                batch.sap_response_data = response_data

                batch.save(
                    update_fields=[
                        "sap_error_message",
                        "sap_response_data",
                        "updated_at",
                    ]
                )

                send_error = SapPurchaseRequestSendError(
                    error_message
                )

            else:
                batch.sap_doc_entry = int(
                    doc_entry
                )
                batch.sap_doc_num = int(
                    doc_num
                )
                batch.sap_sent_at = timezone.now()
                batch.sap_request_payload = payload
                batch.sap_response_data = response_data
                batch.sap_error_message = ""
                batch.status = (
                    ConsolidationBatch.Status.SENT_TO_SAP
                )

                batch.save(
                    update_fields=[
                        "sap_doc_entry",
                        "sap_doc_num",
                        "sap_sent_at",
                        "sap_request_payload",
                        "sap_response_data",
                        "sap_error_message",
                        "status",
                        "updated_at",
                    ]
                )

                send_result = {
                    "batch_id": batch.pk,
                    "doc_entry": batch.sap_doc_entry,
                    "doc_num": batch.sap_doc_num,
                    "sent_at": batch.sap_sent_at,
                    "response_data": response_data,
                }

        finally:
            try:
                client.logout()
            except Exception:
                # Belge işlemi bittikten sonra logout hatası,
                # asıl sonucu geçersiz hâle getirmemelidir.
                pass

    if send_error is not None:
        raise send_error

    if send_result is None:
        raise SapPurchaseRequestSendError(
            "SAP gönderim işlemi tamamlanamadı."
        )

    return send_result