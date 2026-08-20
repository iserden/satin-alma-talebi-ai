from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from django.conf import settings
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from requests_app.models import PurchaseRequest


class GeminiProcessingError(RuntimeError):
    """Gemini ile form işlenirken oluşan kontrollü hataları temsil eder."""


class GeminiPurchaseRequestItem(BaseModel):
    """Gemini tarafından okunacak tek ürün satırının şeması."""

    row_number: int = Field(
        ge=1,
        le=30,
        description="Formdaki satır numarası.",
    )

    raw_product_name: str = Field(
        default="",
        description="Ürün adının formda görüldüğü veya okunduğu ham biçimi.",
    )

    product_name: str = Field(
        default="",
        description="Ürün adının temizlenmiş biçimi.",
    )

    unit: str = Field(
        default="",
        description="KG, ADET, KOLİ, PAKET veya LİTRE gibi ölçü birimi.",
    )

    week1: float | None = Field(
        default=None,
        ge=0,
        description="Birinci hafta miktarı. Boş veya okunamıyorsa null.",
    )

    week2: float | None = Field(
        default=None,
        ge=0,
        description="İkinci hafta miktarı. Boş veya okunamıyorsa null.",
    )

    week3: float | None = Field(
        default=None,
        ge=0,
        description="Üçüncü hafta miktarı. Boş veya okunamıyorsa null.",
    )

    week4: float | None = Field(
        default=None,
        ge=0,
        description="Dördüncü hafta miktarı. Boş veya okunamıyorsa null.",
    )

    week5: float | None = Field(
        default=None,
        ge=0,
        description="Beşinci hafta miktarı. Boş veya okunamıyorsa null.",
    )

    confidence_score: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "Satırın ürün, birim ve miktarlarının okunmasına ilişkin "
            "0 ile 1 arasındaki yaklaşık güven değeri."
        ),
    )


class GeminiPurchaseRequestResult(BaseModel):
    """Satın alma formunun tamamı için beklenen Gemini çıktısı."""

    business_name: str = Field(
        default="",
        description="Formdaki işletme veya lokasyon adı.",
    )

    authorized_person: str = Field(
        default="",
        description="Formdaki yetkili personelin adı ve soyadı.",
    )

    form_date: str | None = Field(
        default=None,
        description=(
            "Form tarihi. Okunabiliyorsa YYYY-AA-GG formatında, "
            "okunamıyorsa null."
        ),
    )

    form_number: str = Field(
        default="",
        description="Form numarası. Alan boşsa boş metin.",
    )

    raw_ocr_text: str = Field(
        default="",
        description=(
            "Formda görülen üst bilgilerin ve dolu ürün satırlarının "
            "kısa, satır bazlı ham transkripsiyonu."
        ),
    )

    items: list[GeminiPurchaseRequestItem] = Field(
        default_factory=list,
        description="Yalnızca dolu ürün satırları.",
    )


EXTRACTION_PROMPT = """
Bu belge, Türkçe hazırlanmış aylık satın alma talep formudur.

Belgedeki bilgileri dikkatlice oku ve verilen yapılandırılmış çıktı şemasına
uygun şekilde çıkar.

FORM YAPISI:
- Üst bölümde işletme adı, yetkili personel, form tarihi ve form numarası bulunur.
- Ana tabloda satır numarası, serbest yazılmış ürün adı, birim ve
  1. haftadan 5. haftaya kadar miktarlar bulunur.
- Ürün adı ve miktarlar el yazısıyla yazılmış olabilir.

KURALLAR:
1. Yalnızca formda gerçekten görülen bilgileri çıkar.
2. Görülmeyen veya okunamayan bilgileri uydurma.
3. Boş veya güvenilir şekilde okunamayan miktar hücrelerini null yap.
4. Yan yana bulunan iki haftanın miktarlarını tek bir sayıya birleştirme.
5. Her miktarı kendi hafta sütunuyla eşleştir.
6. Yalnızca dolu ürün satırlarını items listesine ekle.
7. Satır numarasını formun sol tarafındaki sıra numarasından al.
8. raw_product_name alanına ürünün formda göründüğü biçimi yaz.
9. product_name alanında yalnızca açık yazım hatalarını düzeltebilirsin.
10. Ürünü herhangi bir SAP koduyla eşleştirme ve SAP kodu üretme.
11. Birimleri büyük harfe dönüştür: KG, ADET, KOLİ, PAKET, LİTRE gibi.
12. Ondalık miktarları sayısal değer olarak döndür.
13. Bir değer belirsizse uydurmak yerine null kullan ve güven değerini düşür.
14. confidence_score yaklaşık bir yardımcı değerdir:
    - Çok net satır: 0.90–1.00
    - Kısmen belirsiz satır: 0.60–0.89
    - Önemli ölçüde belirsiz satır: 0.00–0.59
15. Tarihi mümkünse YYYY-AA-GG biçimine dönüştür.
16. Form numarası boşsa boş metin döndür.
17. Çizgileri, logoları ve tablo başlıklarını ürün olarak kabul etme.

Özellikle rakamların hangi haftaya ait olduğunu dikkatlice kontrol et.
"""


SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
}


def determine_mime_type(file_path: Path) -> str:
    """Dosyanın Gemini'ye gönderilecek MIME türünü belirler."""

    mime_type, _ = mimetypes.guess_type(file_path.name)

    suffix = file_path.suffix.lower()

    if suffix in {".jpg", ".jpeg"}:
        mime_type = "image/jpeg"
    elif suffix == ".png":
        mime_type = "image/png"
    elif suffix == ".webp":
        mime_type = "image/webp"
    elif suffix == ".pdf":
        mime_type = "application/pdf"

    if mime_type not in SUPPORTED_MIME_TYPES:
        raise GeminiProcessingError(
            f"Gemini tarafından desteklenmeyen dosya türü: {mime_type}"
        )

    return mime_type


def parse_gemini_response(
    response: Any,
) -> GeminiPurchaseRequestResult:
    """Gemini cevabını Pydantic modeliyle doğrular."""

    try:
        if isinstance(
            response.parsed,
            GeminiPurchaseRequestResult,
        ):
            return response.parsed

        if response.parsed is not None:
            return GeminiPurchaseRequestResult.model_validate(
                response.parsed
            )

        if response.text:
            return GeminiPurchaseRequestResult.model_validate_json(
                response.text
            )

    except ValidationError as exc:
        raise GeminiProcessingError(
            f"Gemini cevabı beklenen şemaya uymuyor: {exc}"
        ) from exc

    raise GeminiProcessingError(
        "Gemini boş veya işlenemeyen bir cevap döndürdü."
    )


def extract_purchase_request_with_gemini(
    purchase_request: PurchaseRequest,
) -> dict[str, Any]:
    """
    Yüklenen PDF veya görseli Gemini'ye gönderir ve yapılandırılmış veri döndürür.
    """

    if not settings.GEMINI_API_KEY:
        raise GeminiProcessingError(
            "GEMINI_API_KEY bulunamadı. .env dosyasını kontrol edin."
        )

    if not purchase_request.source_file:
        raise GeminiProcessingError(
            "İşlenecek satın alma talep dosyası bulunamadı."
        )

    file_path = Path(purchase_request.source_file.path)

    if not file_path.exists():
        raise GeminiProcessingError(
            f"Yüklenen dosya fiziksel olarak bulunamadı: {file_path}"
        )

    mime_type = determine_mime_type(file_path)

    try:
        file_bytes = file_path.read_bytes()

    except OSError as exc:
        raise GeminiProcessingError(
            f"Yüklenen dosya okunamadı: {exc}"
        ) from exc

    file_part = types.Part.from_bytes(
        data=file_bytes,
        mime_type=mime_type,
    )

    # Google'ın belge önerisine uygun olarak PDF'de dosyayı önce,
    # tek görselde ise açıklama metnini önce gönderiyoruz.
    if mime_type == "application/pdf":
        contents = [
            file_part,
            EXTRACTION_PROMPT,
        ]
    else:
        contents = [
            EXTRACTION_PROMPT,
            file_part,
        ]

    client = genai.Client(
        api_key=settings.GEMINI_API_KEY,
    )

    try:
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GeminiPurchaseRequestResult,
            ),
        )

    except Exception as exc:
        raise GeminiProcessingError(
            f"Gemini API isteği başarısız oldu: {exc}"
        ) from exc

    finally:
        client.close()

    parsed_result = parse_gemini_response(response)

    return parsed_result.model_dump(
        mode="json",
    )