from decimal import Decimal

from django import forms
from django.core.validators import FileExtensionValidator
from django.forms import inlineformset_factory

from .models import Product, PurchaseRequest, PurchaseRequestLine


class PurchaseRequestUploadForm(forms.ModelForm):
    class Meta:
        model = PurchaseRequest
        fields = ["source_file"]

        widgets = {
            "source_file": forms.ClearableFileInput(
                attrs={
                    "accept": ".pdf,.png,.jpg,.jpeg,.webp",
                    "class": "file-input",
                }
            )
        }

        labels = {
            "source_file": "Satın alma talep formu",
        }

        help_texts = {
            "source_file": (
                "PDF, PNG, JPG, JPEG veya WEBP formatında bir dosya yükleyin."
            )
        }

    def clean_source_file(self):
        uploaded_file = self.cleaned_data["source_file"]

        maximum_size = 10 * 1024 * 1024

        if uploaded_file.size > maximum_size:
            raise forms.ValidationError(
                "Yüklenen dosya 10 MB boyutundan büyük olamaz."
            )

        return uploaded_file


class PurchaseRequestInfoForm(forms.ModelForm):
    """Formun üst kısmındaki işletme ve belge bilgileri."""

    class Meta:
        model = PurchaseRequest

        fields = [
            "business_name",
            "authorized_person",
            "form_date",
            "form_number",
        ]

        widgets = {
            "business_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Örnek: Deneme Restoran",
                }
            ),
            "authorized_person": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ad Soyad",
                }
            ),
            "form_date": forms.DateInput(
                attrs={
                    "class": "form-control",
                    "type": "date",
                },
                format="%Y-%m-%d",
            ),
            "form_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Örnek: SAT-2026-001",
                }
            ),
        }


class ProductChoiceField(forms.ModelChoiceField):
    """
    Açılır listedeki ürünleri SAP kodu, ürün adı ve birimle gösterir.
    """

    def label_from_instance(self, product):
        label = (
            f"{product.sap_item_code} — "
            f"{product.item_name}"
        )

        if product.unit:
            label += f" ({product.unit})"

        return label


class PurchaseRequestLineForm(forms.ModelForm):
    """Tek bir ürün satırını düzenleyen form."""

    matched_product = ProductChoiceField(
        queryset=Product.objects.none(),
        required=False,
        empty_label="— Katalog ürünü seçin —",
        label="Eşleşen katalog ürünü",
        widget=forms.Select(
            attrs={
                "class": "catalog-product-select",
            }
        ),
    )

    save_as_alias = forms.BooleanField(
        required=False,
        label="Bu ürün adını alternatif ad olarak kaydet",
        widget=forms.CheckboxInput(
            attrs={
                "class": "save-as-alias-checkbox",
            }
        ),
        help_text=(
            "Düzeltilmiş ürün adı, seçilen katalog ürününün "
            "alternatif adı olarak kaydedilir."
        ),
    )

    class Meta:
        model = PurchaseRequestLine

        fields = [
            "row_number",
            "product_name",
            "unit",
            "week1",
            "week2",
            "week3",
            "week4",
            "week5",
            "matched_product",
            "status",
        ]

        widgets = {
            "row_number": forms.NumberInput(
                attrs={
                    "class": "table-input row-number-input",
                    "min": 1,
                    "max": 30,
                }
            ),
            "product_name": forms.TextInput(
                attrs={
                    "class": "table-input product-input",
                    "placeholder": "Ürün adı",
                }
            ),
            "unit": forms.TextInput(
                attrs={
                    "class": "table-input unit-input",
                    "placeholder": "KG",
                }
            ),
            "week1": forms.NumberInput(
                attrs={
                    "class": "table-input quantity-input",
                    "step": "0.01",
                    "min": "0",
                }
            ),
            "week2": forms.NumberInput(
                attrs={
                    "class": "table-input quantity-input",
                    "step": "0.01",
                    "min": "0",
                }
            ),
            "week3": forms.NumberInput(
                attrs={
                    "class": "table-input quantity-input",
                    "step": "0.01",
                    "min": "0",
                }
            ),
            "week4": forms.NumberInput(
                attrs={
                    "class": "table-input quantity-input",
                    "step": "0.01",
                    "min": "0",
                }
            ),
            "week5": forms.NumberInput(
                attrs={
                    "class": "table-input quantity-input",
                    "step": "0.01",
                    "min": "0",
                }
            ),
            "status": forms.Select(
                attrs={
                    "class": "table-input status-input",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["matched_product"].queryset = (
            Product.objects.filter(
                is_active=True,
            ).order_by(
                "item_name",
            )
        )

    def clean(self):
        cleaned_data = super().clean()

        product_name = cleaned_data.get("product_name")
        unit = cleaned_data.get("unit")

        quantities = [
            cleaned_data.get("week1"),
            cleaned_data.get("week2"),
            cleaned_data.get("week3"),
            cleaned_data.get("week4"),
            cleaned_data.get("week5"),
        ]

        has_quantity = any(
            quantity is not None
            for quantity in quantities
        )

        if has_quantity and not product_name:
            self.add_error(
                "product_name",
                "Miktar girilen satırda ürün adı boş bırakılamaz.",
            )

        if product_name and not unit:
            self.add_error(
                "unit",
                "Ürün girilen satırda birim belirtilmelidir.",
            )

        return cleaned_data

    def save(self, commit=True):
        """
        Yönetici katalog ürününü manuel değiştirdiğinde
        eşleştirme bilgilerini otomatik günceller.
        """

        instance = super().save(commit=False)

        changed_fields = set(self.changed_data)

        manual_product_changed = (
            "matched_product" in changed_fields
        )

        product_text_changed = bool(
            {
                "product_name",
                "unit",
            }
            & changed_fields
        )

        if manual_product_changed:
            if instance.matched_product_id:
                instance.matching_status = (
                    PurchaseRequestLine
                    .MatchingStatus
                    .MATCHED
                )

                instance.matching_method = (
                    PurchaseRequestLine
                    .MatchingMethod
                    .MANUAL
                )

                instance.matching_confidence = Decimal(
                    "1.0000"
                )

            else:
                instance.matching_status = (
                    PurchaseRequestLine
                    .MatchingStatus
                    .NOT_MATCHED
                )

                instance.matching_method = (
                    PurchaseRequestLine
                    .MatchingMethod
                    .NONE
                )

                instance.matching_confidence = None

        if commit:
            instance.save()

            # Ürün adı veya birim değiştirilmişse eşleştirmeyi
            # tekrar çalıştırır. Daha önce manuel eşleştirilen
            # kayıtlar otomatik olarak ezilmez.
            has_existing_manual_match = (
                instance.matching_method
                == PurchaseRequestLine
                .MatchingMethod
                .MANUAL
                and instance.matched_product_id
            )

            if (
                product_text_changed
                and not manual_product_changed
                and not has_existing_manual_match
            ):
                from .services.product_matching_service import (
                    match_purchase_request_line,
                )

                match_purchase_request_line(
                    line=instance,
                    save=True,
                )

        return instance


PurchaseRequestLineFormSet = inlineformset_factory(
    parent_model=PurchaseRequest,
    model=PurchaseRequestLine,
    form=PurchaseRequestLineForm,
    extra=5,
    can_delete=True,
    max_num=30,
    validate_max=True,
)


class ProductExcelImportForm(forms.Form):
    """Ürün kataloğunun Excel üzerinden yüklenmesini sağlar."""

    excel_file = forms.FileField(
        label="Ürün kataloğu Excel dosyası",
        validators=[
            FileExtensionValidator(
                allowed_extensions=["xlsx"],
            )
        ],
        widget=forms.ClearableFileInput(
            attrs={
                "accept": ".xlsx",
                "class": "vTextField",
            }
        ),
        help_text=(
            "Yalnızca .xlsx dosyaları kabul edilir. "
            "Maksimum dosya boyutu 10 MB'dır."
        ),
    )

    def clean_excel_file(self):
        excel_file = self.cleaned_data["excel_file"]

        maximum_size = 10 * 1024 * 1024

        if excel_file.size > maximum_size:
            raise forms.ValidationError(
                "Excel dosyası 10 MB'dan büyük olamaz."
            )

        return excel_file


class ApprovedPurchaseRequestChoiceField(
    forms.ModelMultipleChoiceField
):
    """Onaylı formları anlaşılır etiketlerle gösterir."""

    def label_from_instance(self, purchase_request):
        business_name = (
            purchase_request.business_name
            or "İşletme belirtilmemiş"
        )

        form_date = (
            purchase_request.form_date.strftime("%d.%m.%Y")
            if purchase_request.form_date
            else "Tarih belirtilmemiş"
        )

        return (
            f"Talep #{purchase_request.pk} — "
            f"{business_name} — {form_date}"
        )


class ConsolidationCreateForm(forms.Form):
    title = forms.CharField(
        max_length=200,
        label="Birleştirme adı",
        widget=forms.TextInput(
            attrs={
                "placeholder": (
                    "Örnek: Ağustos 2026 satın alma talepleri"
                ),
            }
        ),
    )

    purchase_requests = ApprovedPurchaseRequestChoiceField(
        queryset=PurchaseRequest.objects.none(),
        required=True,
        label="Birleştirilecek onaylı formlar",
        widget=forms.CheckboxSelectMultiple(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["purchase_requests"].queryset = (
            PurchaseRequest.objects
            .filter(
                status=PurchaseRequest.Status.APPROVED,
                consolidation_source__isnull=True,
            )
            .order_by(
                "form_date",
                "pk",
            )
        )
