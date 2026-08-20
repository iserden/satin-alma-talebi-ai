from datetime import date, timedelta
import logging

from django.contrib import messages
from django.contrib.admin.views.decorators import (
    staff_member_required,
)
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import (
    FileResponse,
    HttpResponse,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import (
    require_GET,
    require_POST,
)

from .forms import (
    ConsolidationCreateForm,
    PurchaseRequestInfoForm,
    PurchaseRequestLineFormSet,
    PurchaseRequestUploadForm,
)
from .models import (
    ConsolidationBatch,
    PurchaseRequest,
    PurchaseRequestLine,
)
from .services.ai_result_service import (
    AIResultValidationError,
    apply_ai_result,
    load_demo_ai_result,
)
from .services.alias_learning_service import (
    learn_product_alias,
)
from .services.approval_service import (
    PurchaseRequestApprovalError,
    approve_purchase_request,
    validate_purchase_request_for_approval,
)
from .services.consolidation_service import (
    ConsolidationError,
    create_consolidation_batch,
)
from .services.consolidation_export_service import (
    ConsolidationExportError,
    build_consolidation_csv,
    build_consolidation_excel,
    build_consolidation_json_payload,
    build_export_filename,
    mark_batch_as_exported,
)
from .services.gemini_service import (
    GeminiProcessingError,
    extract_purchase_request_with_gemini,
)
from .services.sap_purchase_request_builder import (
    build_purchase_request_payload,
)
from .services.sap_purchase_request_service import (
    SapPurchaseRequestSendError,
    send_consolidation_batch_to_sap,
)


logger = logging.getLogger(__name__)


def home(request):
    """
    Form yükleme, özet bilgiler ve yüklenen formlar listesini gösterir.
    """

    all_requests = PurchaseRequest.objects.all()

    if request.method == "POST":
        form = PurchaseRequestUploadForm(
            request.POST,
            request.FILES,
        )

        if form.is_valid():
            purchase_request = form.save()

            messages.success(
                request,
                "Satın alma talep formu başarıyla yüklendi.",
            )

            return redirect(
                "requests_app:request_detail",
                pk=purchase_request.pk,
            )
    else:
        form = PurchaseRequestUploadForm()

    search_query = request.GET.get(
        "q",
        "",
    ).strip()

    status_filter = request.GET.get(
        "status",
        "",
    ).strip()

    filtered_requests = all_requests

    if search_query:
        filtered_requests = filtered_requests.filter(
            Q(source_file__icontains=search_query)
            | Q(business_name__icontains=search_query)
            | Q(authorized_person__icontains=search_query)
            | Q(form_number__icontains=search_query)
        )

    valid_statuses = {
        value
        for value, label in PurchaseRequest.Status.choices
    }

    if status_filter in valid_statuses:
        filtered_requests = filtered_requests.filter(
            status=status_filter,
        )
    else:
        status_filter = ""

    filtered_requests = filtered_requests.order_by(
        "-created_at",
    )

    paginator = Paginator(
        filtered_requests,
        10,
    )

    page_obj = paginator.get_page(
        request.GET.get("page")
    )

    processed_statuses = [
        PurchaseRequest.Status.REVIEW_REQUIRED,
        PurchaseRequest.Status.APPROVED,
    ]

    context = {
        "form": form,
        "page_obj": page_obj,
        "purchase_requests": page_obj.object_list,

        "total_count": all_requests.count(),

        "review_count": all_requests.filter(
            status=PurchaseRequest.Status.REVIEW_REQUIRED,
        ).count(),

        "processed_count": all_requests.filter(
            status__in=processed_statuses,
        ).count(),

        "today_count": all_requests.filter(
            created_at__date=timezone.localdate(),
        ).count(),

        "search_query": search_query,
        "status_filter": status_filter,
        "status_choices": PurchaseRequest.Status.choices,
    }

    return render(
        request,
        "requests_app/home.html",
        context,
    )


def request_detail(request, pk):
    """Form üst bilgilerini ve ürün satırlarını düzenler."""

    purchase_request = get_object_or_404(
        PurchaseRequest,
        pk=pk,
    )

    is_approved = (
        purchase_request.status
        == PurchaseRequest.Status.APPROVED
    )

    if request.method == "POST" and is_approved:
        messages.warning(
            request,
            (
                "Onaylanmış bir form düzenlenemez. "
                "Formu yeniden kontrole açma özelliği daha sonra "
                "eklenecektir."
            ),
        )

        return redirect(
            "requests_app:request_detail",
            pk=purchase_request.pk,
        )

    line_queryset = purchase_request.lines.all()

    line_count = line_queryset.count()

    matched_count = line_queryset.filter(
        matching_status=(
            PurchaseRequestLine.MatchingStatus.MATCHED
        )
    ).count()

    matching_review_count = line_queryset.filter(
        matching_status=(
            PurchaseRequestLine.MatchingStatus.REVIEW_REQUIRED
        )
    ).count()

    not_matched_count = line_queryset.filter(
        matching_status=(
            PurchaseRequestLine.MatchingStatus.NOT_MATCHED
        )
    ).count()

    if request.method == "POST":
        info_form = PurchaseRequestInfoForm(
            request.POST,
            instance=purchase_request,
            prefix="info",
        )

        line_formset = PurchaseRequestLineFormSet(
            request.POST,
            instance=purchase_request,
            prefix="lines",
        )

        if info_form.is_valid() and line_formset.is_valid():
            with transaction.atomic():
                updated_request = info_form.save(commit=False)

                updated_request.status = (
                    PurchaseRequest.Status.REVIEW_REQUIRED
                )

                updated_request.save()

                line_formset.instance = updated_request

                # PurchaseRequestLineForm içindeki save() metodu
                # burada manuel eşleştirme alanlarını da günceller.
                line_formset.save()

                created_alias_messages: list[str] = []
                alias_information_messages: list[str] = []
                alias_warning_messages: list[str] = []

                for line_form in line_formset.forms:
                    cleaned_data = getattr(
                        line_form,
                        "cleaned_data",
                        {},
                    )

                    # Silinen satırlar için alias işlemi yapılmaz.
                    if cleaned_data.get("DELETE"):
                        continue

                    # Kullanıcı katalog ürününü değiştirmediyse
                    # alternatif ad öğrenme işlemi yapılmaz.
                    if "matched_product" not in line_form.changed_data:
                        continue

                    # Checkbox işaretli değilse işlem yapılmaz.
                    if not cleaned_data.get("save_as_alias"):
                        continue

                    line = line_form.instance

                    alias_result = learn_product_alias(
                        alias_text=(
                            line.product_name
                            or line.raw_product_name
                        ),
                        product=line.matched_product,
                    )

                    if alias_result.code == "CREATED":
                        created_alias_messages.append(
                            alias_result.message
                        )

                    elif alias_result.code in {
                        "ALREADY_EXISTS",
                        "SAME_AS_PRODUCT",
                    }:
                        alias_information_messages.append(
                            alias_result.message
                        )

                    else:
                        alias_warning_messages.append(
                            alias_result.message
                        )

            messages.success(
                request,
                "Form bilgileri ve ürün satırları kaydedildi.",
            )

            for message_text in created_alias_messages:
                messages.success(
                    request,
                    message_text,
                )

            for message_text in alias_information_messages:
                messages.info(
                    request,
                    message_text,
                )

            for message_text in alias_warning_messages:
                messages.warning(
                    request,
                    message_text,
                )

            return redirect(
                "requests_app:request_detail",
                pk=purchase_request.pk,
            )

        messages.error(
            request,
            "Bazı alanlarda hata bulundu. Lütfen işaretlenen alanları kontrol edin.",
        )

    else:
        info_form = PurchaseRequestInfoForm(
            instance=purchase_request,
            prefix="info",
        )

        line_formset = PurchaseRequestLineFormSet(
            instance=purchase_request,
            prefix="lines",
        )

    if is_approved:
        for field in info_form.fields.values():
            field.disabled = True

        for line_form in line_formset.forms:
            for field in line_form.fields.values():
                field.disabled = True

    approval_issues = (
        []
        if is_approved
        else validate_purchase_request_for_approval(
            purchase_request
        )
    )

    can_approve = (
        not is_approved
        and not approval_issues
    )

    context = {
        "purchase_request": purchase_request,
        "info_form": info_form,
        "line_formset": line_formset,

        "line_count": line_count,
        "matched_count": matched_count,
        "matching_review_count": matching_review_count,
        "not_matched_count": not_matched_count,

        "is_approved": is_approved,
        "approval_issues": approval_issues,
        "can_approve": can_approve,
    }

    return render(
        request,
        "requests_app/detail.html",
        context,
    )


@require_POST
def demo_process(request, pk):
    """Demo JSON sonucunu seçilen satın alma formuna uygular."""

    purchase_request = get_object_or_404(
        PurchaseRequest,
        pk=pk,
    )

    purchase_request.status = (
        PurchaseRequest.Status.PROCESSING
    )

    purchase_request.error_message = ""

    purchase_request.save(
        update_fields=[
            "status",
            "error_message",
            "updated_at",
        ]
    )

    try:
        demo_data = load_demo_ai_result()

        apply_ai_result(
            purchase_request=purchase_request,
            data=demo_data,
        )

    except AIResultValidationError as exc:
        purchase_request.status = (
            PurchaseRequest.Status.FAILED
        )

        purchase_request.error_message = str(exc)

        purchase_request.save(
            update_fields=[
                "status",
                "error_message",
                "updated_at",
            ]
        )

        messages.error(
            request,
            f"Demo AI sonucu işlenemedi: {exc}",
        )

    except Exception:
        logger.exception(
            "Demo AI işlemi sırasında beklenmeyen hata oluştu."
        )

        purchase_request.status = (
            PurchaseRequest.Status.FAILED
        )

        purchase_request.error_message = (
            "Demo AI işlemi sırasında beklenmeyen bir hata oluştu."
        )

        purchase_request.save(
            update_fields=[
                "status",
                "error_message",
                "updated_at",
            ]
        )

        messages.error(
            request,
            "Demo AI işlemi sırasında beklenmeyen bir hata oluştu.",
        )

    else:
        messages.success(
            request,
            (
                "Demo AI sonucu doğrulandı ve "
                "veritabanına başarıyla aktarıldı."
            ),
        )

    return redirect(
        "requests_app:request_detail",
        pk=purchase_request.pk,
    )


@require_POST
def gemini_process(request, pk):
    """Yüklenen satın alma formunu Gemini ile işler."""

    purchase_request = get_object_or_404(
        PurchaseRequest,
        pk=pk,
    )

    if purchase_request.status == PurchaseRequest.Status.APPROVED:
        messages.warning(
            request,
            (
                "Onaylanmış bir talep formu Gemini ile yeniden "
                "işlenemez."
            ),
        )

        return redirect(
            "requests_app:request_detail",
            pk=purchase_request.pk,
        )

    purchase_request.status = (
        PurchaseRequest.Status.PROCESSING
    )

    purchase_request.error_message = ""

    purchase_request.save(
        update_fields=[
            "status",
            "error_message",
            "updated_at",
        ]
    )

    try:
        gemini_data = extract_purchase_request_with_gemini(
            purchase_request=purchase_request,
        )

        apply_ai_result(
            purchase_request=purchase_request,
            data=gemini_data,
        )

    except (
        GeminiProcessingError,
        AIResultValidationError,
    ) as exc:
        purchase_request.status = (
            PurchaseRequest.Status.FAILED
        )

        purchase_request.error_message = str(exc)

        purchase_request.save(
            update_fields=[
                "status",
                "error_message",
                "updated_at",
            ]
        )

        messages.error(
            request,
            f"Gemini işlemi tamamlanamadı: {exc}",
        )

    except Exception:
        logger.exception(
            "Gemini işlemi sırasında beklenmeyen hata oluştu."
        )

        purchase_request.status = (
            PurchaseRequest.Status.FAILED
        )

        purchase_request.error_message = (
            "Gemini işlemi sırasında beklenmeyen bir hata oluştu."
        )

        purchase_request.save(
            update_fields=[
                "status",
                "error_message",
                "updated_at",
            ]
        )

        messages.error(
            request,
            "Gemini işlemi sırasında beklenmeyen bir hata oluştu.",
        )

    else:
        messages.success(
            request,
            (
                "Form Gemini tarafından okundu, doğrulandı "
                "ve veritabanına aktarıldı."
            ),
        )

    return redirect(
        "requests_app:request_detail",
        pk=purchase_request.pk,
    )


@staff_member_required
@require_POST
def approve_request(request, pk):
    """
    Yetkili kullanıcının satın alma talep formunu onaylamasını sağlar.
    """

    purchase_request = get_object_or_404(
        PurchaseRequest,
        pk=pk,
    )

    if purchase_request.status == PurchaseRequest.Status.APPROVED:
        messages.info(
            request,
            "Bu satın alma talep formu zaten onaylanmış.",
        )

        return redirect(
            "requests_app:request_detail",
            pk=purchase_request.pk,
        )

    try:
        approved_request = approve_purchase_request(
            purchase_request_id=purchase_request.pk,
            approved_by=request.user,
        )

    except PurchaseRequestApprovalError as exc:
        messages.error(
            request,
            "Form onaylanamadı. Aşağıdaki eksikleri düzeltin.",
        )

        for issue in exc.issues[:10]:
            messages.warning(
                request,
                issue.message,
            )

        remaining_issue_count = len(exc.issues) - 10

        if remaining_issue_count > 0:
            messages.warning(
                request,
                (
                    f"Gösterilmeyen {remaining_issue_count} "
                    "onay problemi daha bulunuyor."
                ),
            )

    else:
        messages.success(
            request,
            (
                f"Talep #{approved_request.pk} başarıyla onaylandı."
            ),
        )

    return redirect(
        "requests_app:request_detail",
        pk=purchase_request.pk,
    )


@staff_member_required
def consolidation_list(request):
    """Oluşturulmuş birleştirme gruplarını listeler."""

    batches = list(
        ConsolidationBatch.objects
        .select_related("created_by")
        .annotate(
            source_count=Count(
                "sources",
                distinct=True,
            ),
            product_count=Count(
                "lines",
                distinct=True,
            ),
        )
        .order_by("-created_at")
    )

    total_source_forms = sum(
        batch.source_count
        for batch in batches
    )

    total_products = sum(
        batch.product_count
        for batch in batches
    )

    ready_count = sum(
        1
        for batch in batches
        if batch.status == ConsolidationBatch.Status.READY
    )

    return render(
        request,
        "requests_app/consolidations/list.html",
        {
            "batches": batches,
            "total_batches": len(batches),
            "total_source_forms": total_source_forms,
            "total_products": total_products,
            "ready_count": ready_count,
        },
    )


@staff_member_required
def consolidation_create(request):
    """Onaylanmış formlardan yeni bir birleştirme oluşturur."""

    if request.method == "POST":
        form = ConsolidationCreateForm(
            request.POST,
        )

        if form.is_valid():
            selected_requests = form.cleaned_data[
                "purchase_requests"
            ]

            purchase_request_ids = list(
                selected_requests.values_list(
                    "pk",
                    flat=True,
                )
            )

            try:
                batch = create_consolidation_batch(
                    title=form.cleaned_data["title"],
                    purchase_request_ids=purchase_request_ids,
                    created_by=request.user,
                )

            except ConsolidationError as exc:
                form.add_error(
                    None,
                    str(exc),
                )

            else:
                messages.success(
                    request,
                    (
                        f"“{batch.title}” birleştirmesi "
                        "başarıyla oluşturuldu."
                    ),
                )

                return redirect(
                    "requests_app:consolidation_detail",
                    pk=batch.pk,
                )

    else:
        form = ConsolidationCreateForm()

    return render(
        request,
        "requests_app/consolidations/create.html",
        {
            "form": form,
        },
    )


@staff_member_required
@require_GET
def consolidation_sap_preview(request, pk):
    """
    Birleştirme kaydının SAP Business One'a gönderilecek
    satın alma talebi önizlemesini gösterir.
    """

    batch = get_object_or_404(
        ConsolidationBatch.objects.prefetch_related(
            "lines__product",
        ),
        pk=pk,
    )

    required_date_text = request.GET.get("required_date")

    if required_date_text:
        try:
            required_date = date.fromisoformat(required_date_text)
        except ValueError:
            messages.error(
                request,
                "Gerekli tarih geçerli bir tarih olmalıdır.",
            )
            return redirect(
                "requests_app:consolidation_detail",
                pk=batch.pk,
            )
    else:
        required_date = timezone.localdate() + timedelta(days=7)

    try:
        payload = build_purchase_request_payload(
            batch,
            required_date=required_date,
        )
    except ValueError as exc:
        messages.error(
            request,
            str(exc),
        )
        return redirect(
            "requests_app:consolidation_detail",
            pk=batch.pk,
        )

    batch_lines = {
        line.product.sap_item_code: line
        for line in batch.lines.all()
    }

    preview_lines = []

    for document_line in payload["DocumentLines"]:
        source_line = batch_lines.get(
            document_line["ItemCode"]
        )

        preview_lines.append(
            {
                "item_code": document_line["ItemCode"],
                "item_name": (
                    source_line.product.item_name
                    if source_line
                    else "-"
                ),
                "quantity": document_line["Quantity"],
                "unit": (
                    source_line.unit
                    if source_line
                    else "-"
                ),
                "warehouse_code": document_line["WarehouseCode"],
            }
        )

    return render(
        request,
        "requests_app/consolidations/sap_preview.html",
        {
            "batch": batch,
            "payload": payload,
            "preview_lines": preview_lines,
            "required_date": required_date,
            "line_count": len(preview_lines),
        },
    )


@staff_member_required
@require_POST
def consolidation_send_to_sap(request, pk):
    """
    Birleştirme kaydını SAP Business One'a
    satın alma talebi olarak gönderir.
    """

    batch = get_object_or_404(
        ConsolidationBatch,
        pk=pk,
    )

    required_date_text = request.POST.get(
        "required_date",
        "",
    )

    try:
        required_date = date.fromisoformat(
            required_date_text
        )
    except ValueError:
        messages.error(
            request,
            "SAP gönderimi için geçerli bir gerekli tarih seçmelisin.",
        )

        return redirect(
            "requests_app:consolidation_sap_preview",
            pk=batch.pk,
        )

    try:
        result = send_consolidation_batch_to_sap(
            batch_id=batch.pk,
            required_date=required_date,
        )

    except SapPurchaseRequestSendError as exc:
        messages.error(
            request,
            f"SAP gönderimi başarısız oldu: {exc}",
        )

        return redirect(
            (
                "requests_app:consolidation_sap_preview"
            ),
            pk=batch.pk,
        )

    messages.success(
        request,
        (
            "Satın alma talebi SAP Business One'a gönderildi. "
            f"Belge numarası: {result['doc_num']} | "
            f"DocEntry: {result['doc_entry']}"
        ),
    )

    return redirect(
        "requests_app:consolidation_sap_preview",
        pk=batch.pk,
    )


@staff_member_required
def consolidation_detail(request, pk):
    """Birleştirilmiş ürün miktarlarını gösterir."""

    batch = get_object_or_404(
        ConsolidationBatch.objects
        .select_related("created_by")
        .prefetch_related(
            "sources__purchase_request",
            "lines__product",
        ),
        pk=pk,
    )

    source_forms = [
        source.purchase_request
        for source in batch.sources.all()
    ]

    consolidated_lines = batch.lines.all()

    return render(
        request,
        "requests_app/consolidations/detail.html",
        {
            "batch": batch,
            "source_forms": source_forms,
            "consolidated_lines": consolidated_lines,
        },
    )


@staff_member_required
@require_GET
def consolidation_export_excel(request, pk):
    """Birleştirme sonucunu Excel olarak indirir."""

    batch = get_object_or_404(
        ConsolidationBatch,
        pk=pk,
    )

    try:
        excel_file = build_consolidation_excel(
            batch
        )

    except ConsolidationExportError as exc:
        messages.error(
            request,
            str(exc),
        )

        return redirect(
            "requests_app:consolidation_detail",
            pk=batch.pk,
        )

    mark_batch_as_exported(batch)

    filename = build_export_filename(
        batch,
        "xlsx",
    )

    return FileResponse(
        excel_file,
        as_attachment=True,
        filename=filename,
        content_type=(
            "application/vnd.openxmlformats-"
            "officedocument.spreadsheetml.sheet"
        ),
    )


@staff_member_required
@require_GET
def consolidation_export_csv(request, pk):
    """Birleştirme sonucunu CSV olarak indirir."""

    batch = get_object_or_404(
        ConsolidationBatch,
        pk=pk,
    )

    try:
        csv_content = build_consolidation_csv(
            batch
        )

    except ConsolidationExportError as exc:
        messages.error(
            request,
            str(exc),
        )

        return redirect(
            "requests_app:consolidation_detail",
            pk=batch.pk,
        )

    mark_batch_as_exported(batch)

    filename = build_export_filename(
        batch,
        "csv",
    )

    response = HttpResponse(
        csv_content,
        content_type=(
            "text/csv; charset=utf-8"
        ),
    )

    response["Content-Disposition"] = (
        f'attachment; filename="{filename}"'
    )

    return response


@staff_member_required
@require_GET
def consolidation_export_json(request, pk):
    """Birleştirme sonucunu JSON olarak indirir."""

    batch = get_object_or_404(
        ConsolidationBatch,
        pk=pk,
    )

    try:
        payload = build_consolidation_json_payload(
            batch
        )

    except ConsolidationExportError as exc:
        messages.error(
            request,
            str(exc),
        )

        return redirect(
            "requests_app:consolidation_detail",
            pk=batch.pk,
        )

    mark_batch_as_exported(batch)

    filename = build_export_filename(
        batch,
        "json",
    )

    response = JsonResponse(
        payload,
        json_dumps_params={
            "ensure_ascii": False,
            "indent": 2,
        },
    )

    response["Content-Disposition"] = (
        f'attachment; filename="{filename}"'
    )

    return response
