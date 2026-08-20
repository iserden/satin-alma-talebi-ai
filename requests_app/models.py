from decimal import Decimal

from django.conf import settings
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models
from pathlib import Path

from .utils import normalize_product_text


class PurchaseRequest(models.Model):
    """Sisteme yüklenen satın alma talep formunu temsil eder."""

    class Status(models.TextChoices):
        UPLOADED = "UPLOADED", "Yüklendi"
        PROCESSING = "PROCESSING", "İşleniyor"
        REVIEW_REQUIRED = "REVIEW_REQUIRED", "Kontrol gerekli"
        APPROVED = "APPROVED", "Onaylandı"
        FAILED = "FAILED", "Hata oluştu"

    source_file = models.FileField(
        upload_to="purchase_requests/%Y/%m/",
        validators=[
            FileExtensionValidator(
                allowed_extensions=["pdf", "png", "jpg", "jpeg", "webp"]
            )
        ],
        verbose_name="Form dosyası",
    )

    business_name = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="İşletme adı",
    )

    authorized_person = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Yetkili personel",
    )

    form_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Form tarihi",
    )

    form_number = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        verbose_name="Form numarası",
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.UPLOADED,
        verbose_name="İşlem durumu",
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Onaylanma zamanı",
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_purchase_requests",
        verbose_name="Onaylayan kullanıcı",
    )

    raw_ocr_text = models.TextField(
        blank=True,
        verbose_name="Ham OCR metni",
    )

    extracted_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Çıkarılan yapılandırılmış veri",
    )

    error_message = models.TextField(
        blank=True,
        verbose_name="Hata mesajı",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Yüklenme tarihi",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Güncellenme tarihi",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Satın alma talebi"
        verbose_name_plural = "Satın alma talepleri"

    @property
    def file_extension(self):
        if not self.source_file:
            return ""

        return Path(self.source_file.name).suffix.lower()

    @property
    def is_image(self):
        return self.file_extension in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
        }

    @property
    def is_pdf(self):
        return self.file_extension == ".pdf"

    def __str__(self):
        if self.form_number:
            return self.form_number

        return f"Talep #{self.pk}"


class Product(models.Model):
    """Şirketin ürün kataloğundaki gerçek ürün kartını temsil eder."""

    sap_item_code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name="SAP kalem kodu",
    )

    item_name = models.CharField(
        max_length=300,
        verbose_name="Ürün adı",
    )

    normalized_name = models.CharField(
        max_length=300,
        blank=True,
        editable=False,
        db_index=True,
        verbose_name="Standartlaştırılmış ürün adı",
    )

    unit = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Birim",
    )

    category = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Kategori",
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Aktif",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["item_name"]
        verbose_name = "Ürün"
        verbose_name_plural = "Ürünler"

    def save(self, *args, **kwargs):
        self.item_name = self.item_name.strip()
        self.unit = self.unit.strip().upper()
        self.normalized_name = normalize_product_text(
            self.item_name
        )

        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.sap_item_code} - "
            f"{self.item_name} ({self.unit})"
        )


class ProductAlias(models.Model):
    """
    Bir ürünün depo çalışanları tarafından kullanılabilecek
    alternatif yazım biçimini temsil eder.
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="aliases",
        verbose_name="Bağlı ürün",
    )

    alias_name = models.CharField(
        max_length=300,
        verbose_name="Alternatif ürün adı",
    )

    normalized_alias = models.CharField(
        max_length=300,
        blank=True,
        editable=False,
        db_index=True,
        verbose_name="Standartlaştırılmış alternatif ad",
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Aktif",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["alias_name"]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "product",
                    "normalized_alias",
                ],
                name="unique_product_normalized_alias",
            )
        ]

        verbose_name = "Ürün alternatif adı"
        verbose_name_plural = "Ürün alternatif adları"

    def save(self, *args, **kwargs):
        self.alias_name = self.alias_name.strip()
        self.normalized_alias = normalize_product_text(
            self.alias_name
        )

        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.alias_name} → "
            f"{self.product.item_name}"
        )


class PurchaseRequestLine(models.Model):
    """Satın alma talep formundaki tek bir ürün satırını temsil eder."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Bekliyor"
        VALID = "VALID", "Geçerli"
        REVIEW_REQUIRED = "REVIEW_REQUIRED", "Kontrol gerekli"
        INVALID = "INVALID", "Geçersiz"

    class MatchingStatus(models.TextChoices):
        NOT_PROCESSED = (
            "NOT_PROCESSED",
            "Henüz eşleştirilmedi",
        )
        MATCHED = (
            "MATCHED",
            "Eşleştirildi",
        )
        REVIEW_REQUIRED = (
            "REVIEW_REQUIRED",
            "Eşleşme kontrolü gerekli",
        )
        NOT_MATCHED = (
            "NOT_MATCHED",
            "Eşleşme bulunamadı",
        )

    class MatchingMethod(models.TextChoices):
        NONE = (
            "NONE",
            "Yöntem yok",
        )
        EXACT_NAME = (
            "EXACT_NAME",
            "Tam ürün adı",
        )
        ALIAS = (
            "ALIAS",
            "Alternatif ürün adı",
        )
        FUZZY = (
            "FUZZY",
            "Benzer metin",
        )
        MANUAL = (
            "MANUAL",
            "Kullanıcı seçimi",
        )

    purchase_request = models.ForeignKey(
        "PurchaseRequest",
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="Bağlı olduğu form",
    )

    row_number = models.PositiveSmallIntegerField(
        verbose_name="Satır numarası",
    )

    raw_product_name = models.CharField(
        max_length=300,
        blank=True,
        verbose_name="OCR tarafından okunan ürün adı",
    )

    product_name = models.CharField(
        max_length=300,
        blank=True,
        verbose_name="Düzeltilmiş ürün adı",
    )

    unit = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Birim",
    )

    matched_product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_request_lines",
        verbose_name="Eşleşen katalog ürünü",
    )

    matching_confidence = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0")),
            MaxValueValidator(Decimal("1")),
        ],
        verbose_name="Eşleştirme güveni",
    )

    matching_status = models.CharField(
        max_length=30,
        choices=MatchingStatus.choices,
        default=MatchingStatus.NOT_PROCESSED,
        verbose_name="Eşleştirme durumu",
    )

    matching_method = models.CharField(
        max_length=30,
        choices=MatchingMethod.choices,
        default=MatchingMethod.NONE,
        verbose_name="Eşleştirme yöntemi",
    )

    week1 = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="1. hafta",
    )

    week2 = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="2. hafta",
    )

    week3 = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="3. hafta",
    )

    week4 = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="4. hafta",
    )

    week5 = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="5. hafta",
    )

    confidence_score = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0")),
            MaxValueValidator(Decimal("1")),
        ],
        verbose_name="Güven skoru",
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="Satır durumu",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["row_number"]

        constraints = [
            models.UniqueConstraint(
                fields=["purchase_request", "row_number"],
                name="unique_request_row_number",
            )
        ]

        verbose_name = "Talep satırı"
        verbose_name_plural = "Talep satırları"

    def __str__(self):
        product = self.product_name or self.raw_product_name or "Boş satır"
        return f"{self.row_number}. satır - {product}"

    @property
    def total_quantity(self):
        """Boş olmayan bütün haftalık miktarları toplar."""

        quantities = [
            self.week1,
            self.week2,
            self.week3,
            self.week4,
            self.week5,
        ]

        return sum(
            (quantity or Decimal("0") for quantity in quantities),
            Decimal("0"),
        )

    @property
    def confidence_percentage(self):
        """0-1 arasındaki güven skorunu yüzde olarak döndürür."""

        if self.confidence_score is None:
            return None

        return round(
            float(self.confidence_score) * 100
        )

    @property
    def matching_confidence_percentage(self):
        """Eşleştirme güvenini yüzde biçiminde döndürür."""

        if self.matching_confidence is None:
            return None

        return (
            self.matching_confidence * Decimal("100")
        ).quantize(
            Decimal("0.01")
        )

    def save(self, *args, **kwargs):
        # Manuel girişte ham ürün adı boş bırakılırsa ürün adını ham değer olarak kullan.
        if self.product_name and not self.raw_product_name:
            self.raw_product_name = self.product_name

        super().save(*args, **kwargs)


class ConsolidationBatch(models.Model):
    """
    Birden fazla onaylı satın alma talebinin tek grupta
    birleştirilmesini temsil eder.
    """

    class Status(models.TextChoices):
        READY = (
            "READY",
            "Hazır",
        )
        EXPORTED = (
            "EXPORTED",
            "Dışa aktarıldı",
        )
        SENT_TO_SAP = (
            "SENT_TO_SAP",
            "SAP sistemine aktarıldı",
        )

    title = models.CharField(
        max_length=200,
        verbose_name="Birleştirme adı",
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.READY,
        verbose_name="Durum",
    )

    sap_doc_entry = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="SAP DocEntry",
    )

    sap_doc_num = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="SAP belge numarası",
    )

    sap_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="SAP'ye gönderilme zamanı",
    )

    sap_error_message = models.TextField(
        blank=True,
        default="",
        verbose_name="SAP hata mesajı",
    )

    sap_request_payload = models.JSONField(
        blank=True,
        default=dict,
        verbose_name="SAP istek verisi",
    )

    sap_response_data = models.JSONField(
        blank=True,
        default=dict,
        verbose_name="SAP cevap verisi",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_consolidation_batches",
        verbose_name="Oluşturan kullanıcı",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Oluşturulma zamanı",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Güncellenme zamanı",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Talep birleştirmesi"
        verbose_name_plural = "Talep birleştirmeleri"

    def __str__(self):
        return f"#{self.pk} — {self.title}"


class ConsolidationSource(models.Model):
    """
    Birleştirme grubuna dahil edilen kaynak satın alma talebidir.

    OneToOneField kullanıldığı için aynı onaylı form iki farklı
    birleştirmeye yanlışlıkla dahil edilemez.
    """

    batch = models.ForeignKey(
        ConsolidationBatch,
        on_delete=models.CASCADE,
        related_name="sources",
        verbose_name="Birleştirme",
    )

    purchase_request = models.OneToOneField(
        PurchaseRequest,
        on_delete=models.PROTECT,
        related_name="consolidation_source",
        verbose_name="Kaynak talep formu",
    )

    added_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Eklenme zamanı",
    )

    class Meta:
        ordering = ["purchase_request_id"]
        verbose_name = "Birleştirme kaynak formu"
        verbose_name_plural = "Birleştirme kaynak formları"

    def __str__(self):
        return (
            f"{self.batch.title} → "
            f"Talep #{self.purchase_request_id}"
        )


class ConsolidationLine(models.Model):
    """
    Kaynak formlardaki aynı katalog ürünlerinin toplanmış sonucudur.
    """

    batch = models.ForeignKey(
        ConsolidationBatch,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="Birleştirme",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="consolidation_lines",
        verbose_name="Katalog ürünü",
    )

    unit = models.CharField(
        max_length=30,
        verbose_name="Birim",
    )

    week1 = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        verbose_name="1. hafta",
    )

    week2 = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        verbose_name="2. hafta",
    )

    week3 = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        verbose_name="3. hafta",
    )

    week4 = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        verbose_name="4. hafta",
    )

    week5 = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        verbose_name="5. hafta",
    )

    source_request_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Kaynak form sayısı",
    )

    source_line_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Kaynak satır sayısı",
    )

    class Meta:
        ordering = ["product__item_name"]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "batch",
                    "product",
                ],
                name="unique_product_per_consolidation_batch",
            )
        ]

        verbose_name = "Birleştirilmiş ürün satırı"
        verbose_name_plural = "Birleştirilmiş ürün satırları"

    @property
    def total_quantity(self):
        return (
            self.week1
            + self.week2
            + self.week3
            + self.week4
            + self.week5
        )

    def __str__(self):
        return (
            f"{self.product.sap_item_code} — "
            f"{self.product.item_name}"
        )
