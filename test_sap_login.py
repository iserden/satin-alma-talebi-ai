import json
import os
import sys

import requests
import urllib3
from dotenv import load_dotenv


load_dotenv()

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)

SERVICE_LAYER_URL = os.getenv(
    "SAP_BASE_URL",
    "https://mersapvm01:50000/b1s/v1",
)

LOGIN_DATA = {
    "CompanyDB": os.getenv("SAP_COMPANY_DB", ""),
    "UserName": os.getenv("SAP_USERNAME", ""),
    "Password": os.getenv("SAP_PASSWORD", ""),
}


def main() -> None:
    login_url = f"{SERVICE_LAYER_URL}/Login"

    print("SAP Service Layer bağlantısı deneniyor...")
    print(f"Adres: {login_url}")

    try:
        response = requests.post(
            login_url,
            json=LOGIN_DATA,
            verify=False,
            timeout=20,
        )
    except requests.RequestException as error:
        print("\nBağlantı kurulamadı.")
        print(f"Hata: {error}")
        sys.exit(1)

    print(f"\nHTTP durum kodu: {response.status_code}")

    try:
        response_data = response.json()
        print(
            "SAP cevabı:",
            json.dumps(
                response_data,
                ensure_ascii=False,
                indent=2,
            ),
        )
    except ValueError:
        print("SAP cevabı:")
        print(response.text)

    if response.ok:
        print("\nSONUÇ: SAP Service Layer girişi başarılı.")
        print(
            "Oturum çerezleri:",
            list(response.cookies.keys()),
        )
    else:
        print("\nSONUÇ: SAP Service Layer girişi başarısız.")
        sys.exit(1)


if __name__ == "__main__":
    main()
