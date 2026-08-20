from __future__ import annotations

from datetime import date, datetime
from typing import Any

import requests
from django.conf import settings


class SapServiceLayerError(Exception):
    """SAP Service Layer işlemlerinde oluşan hataları temsil eder."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        sap_error_code: int | str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.sap_error_code = sap_error_code


class SapServiceLayerClient:
    """
    SAP Business One Service Layer istemcisi.

    Temel görevleri:
    - SAP oturumu açmak
    - Ürün bilgisi okumak
    - Satın alma talebi oluşturmak
    - SAP oturumunu kapatmak
    """

    def __init__(
        self,
        *,
        base_url: str,
        company_db: str,
        username: str,
        password: str,
        verify_ssl: bool = False,
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.company_db = company_db
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.timeout = timeout

        self.session = requests.Session()
        self.is_logged_in = False

    def _build_url(self, endpoint: str) -> str:
        """Service Layer adresini oluşturur."""

        return f"{self.base_url}/{endpoint.lstrip('/')}"

    def _extract_error_message(
        self,
        response: requests.Response,
    ) -> tuple[str, int | str | None]:
        """
        SAP'nin JSON hata cevabından hata mesajını ve kodunu çıkarır.
        """

        try:
            response_data = response.json()
        except ValueError:
            return response.text or "SAP Service Layer bilinmeyen hata döndürdü.", None

        error_data = response_data.get("error", {})
        sap_error_code = error_data.get("code")

        message_data = error_data.get("message", {})

        if isinstance(message_data, dict):
            message = message_data.get("value")
        else:
            message = str(message_data)

        if not message:
            message = response.text or "SAP Service Layer işlemi başarısız oldu."

        return message, sap_error_code

    def _raise_for_sap_error(self, response: requests.Response) -> None:
        """Başarısız SAP cevaplarında Python hatası oluşturur."""

        if response.ok:
            return

        message, sap_error_code = self._extract_error_message(response)

        raise SapServiceLayerError(
            message,
            status_code=response.status_code,
            sap_error_code=sap_error_code,
        )

    def login(self) -> dict[str, Any]:
        """SAP Service Layer oturumu açar."""

        payload = {
            "CompanyDB": self.company_db,
            "UserName": self.username,
            "Password": self.password,
        }

        response = self.session.post(
            self._build_url("Login"),
            json=payload,
            verify=self.verify_ssl,
            timeout=self.timeout,
        )

        self._raise_for_sap_error(response)

        self.is_logged_in = True
        return response.json()

    def logout(self) -> None:
        """Açık SAP Service Layer oturumunu kapatır."""

        if not self.is_logged_in:
            return

        response = self.session.post(
            self._build_url("Logout"),
            verify=self.verify_ssl,
            timeout=self.timeout,
        )

        self._raise_for_sap_error(response)
        self.is_logged_in = False

    def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> requests.Response:
        """
        SAP'ye oturum bilgileriyle istek gönderir.

        Oturum yoksa otomatik olarak login işlemi yapar.
        Oturum zaman aşımına uğrarsa bir kez yeniden giriş yapar.
        """

        if not self.is_logged_in:
            self.login()

        response = self.session.request(
            method=method,
            url=self._build_url(endpoint),
            verify=self.verify_ssl,
            timeout=self.timeout,
            **kwargs,
        )

        if response.status_code == 401:
            self.is_logged_in = False
            self.login()

            response = self.session.request(
                method=method,
                url=self._build_url(endpoint),
                verify=self.verify_ssl,
                timeout=self.timeout,
                **kwargs,
            )

        self._raise_for_sap_error(response)
        return response

    def get_item(self, item_code: str) -> dict[str, Any]:
        """SAP'den tek bir ürün kartını okur."""

        safe_item_code = item_code.replace("'", "''")

        response = self._request(
            "GET",
            f"Items('{safe_item_code}')",
            params={
                "$select": (
                    "ItemCode,"
                    "ItemName,"
                    "PurchaseItem,"
                    "SalesItem,"
                    "InventoryItem,"
                    "DefaultWarehouse"
                )
            },
            headers={
                "Accept": "application/json",
            },
        )

        return response.json()

    def create_purchase_request(
        self,
        *,
        required_date: str | date | datetime,
        document_lines: list[dict[str, Any]],
        comments: str = "",
    ) -> dict[str, Any]:
        """SAP üzerinde satın alma talebi oluşturur."""

        if isinstance(required_date, datetime):
            required_date_value = required_date.date().isoformat()
        elif isinstance(required_date, date):
            required_date_value = required_date.isoformat()
        else:
            required_date_value = required_date

        if not document_lines:
            raise ValueError(
                "Satın alma talebinde en az bir ürün satırı bulunmalıdır."
            )

        normalized_lines: list[dict[str, Any]] = []

        for line_number, line in enumerate(document_lines, start=1):
            item_code = line.get("ItemCode")
            quantity = line.get("Quantity")
            warehouse_code = line.get("WarehouseCode")

            if not item_code:
                raise ValueError(
                    f"{line_number}. satırda ItemCode bulunmuyor."
                )

            if quantity is None or float(quantity) <= 0:
                raise ValueError(
                    f"{line_number}. satırdaki miktar sıfırdan büyük olmalıdır."
                )

            if not warehouse_code:
                raise ValueError(
                    f"{line_number}. satırda WarehouseCode bulunmuyor."
                )

            normalized_lines.append(
                {
                    "ItemCode": item_code,
                    "Quantity": quantity,
                    "WarehouseCode": warehouse_code,
                }
            )

        payload = {
            # SAP Service Layer bu alanı bu yazımla kabul etti.
            "RequriedDate": required_date_value,
            "Comments": comments,
            "DocumentLines": normalized_lines,
        }

        response = self._request(
            "POST",
            "PurchaseRequests",
            json=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

        return response.json()


def get_sap_client() -> SapServiceLayerClient:
    """
    Django settings.py içindeki SAP bağlantı ayarlarıyla
    yeni bir Service Layer istemcisi oluşturur.
    """

    sap_settings = settings.SAP_SERVICE_LAYER

    return SapServiceLayerClient(
        base_url=sap_settings["BASE_URL"],
        company_db=sap_settings["COMPANY_DB"],
        username=sap_settings["USERNAME"],
        password=sap_settings["PASSWORD"],
        verify_ssl=sap_settings["VERIFY_SSL"],
        timeout=sap_settings["TIMEOUT"],
    )