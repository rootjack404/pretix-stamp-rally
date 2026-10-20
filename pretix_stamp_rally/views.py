import csv
import json

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.translation import gettext as gettext_now
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, ListView, TemplateView, UpdateView, View
from pretix.base.models import Event
from pretix.control.permissions import EventPermissionRequiredMixin
from pretix.control.views.event import EventSettingsFormView, EventSettingsViewMixin
from pretix.helpers.compat import CompatDeleteView
from pretix.multidomain.urlreverse import eventreverse

from .forms import BoothForm, RaffleDrawForm, StampRallySettingsForm
from .models import StampRallyBooth, StampRallyDraw, StampRallyWinner
from .services import (
    RaffleError,
    active_booths,
    attendee_label,
    collect_stamp,
    describe_participation,
    draw_raffle,
    filter_by_participation,
    spin_raffle,
    normalize_participation_filter,
    participation_counts,
    progress_queryset,
    raffle_pool_counts,
    required_stamp_count,
    void_raffle,
)


def _read_scan_code(request):
    code = request.POST.get("code")
    if code:
        return code
    if request.content_type and "json" in request.content_type:
        try:
            return json.loads(request.body.decode() or "{}").get("code")
        except ValueError:
            return None
    return None


class BoothQueryMixin:
    def get_queryset(self):
        return self.request.event.stamp_rally_booths.all()


class BoothListView(EventPermissionRequiredMixin, BoothQueryMixin, ListView):
    model = StampRallyBooth
    permission = "event.settings.general:write"
    template_name = "pretix_stamp_rally/control_booths.html"
    context_object_name = "booths"

    def get_queryset(self):
        return super().get_queryset().annotate(stamp_total=Count("stamps"))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["required"] = required_stamp_count(self.request.event)
        ctx["active_count"] = self.get_queryset().filter(active=True).count()
        return ctx


class BoothCreateView(EventPermissionRequiredMixin, CreateView):
    model = StampRallyBooth
    form_class = BoothForm
    template_name = "pretix_stamp_rally/control_booth_form.html"
    permission = "event.settings.general:write"

    def get_success_url(self):
        return reverse(
            "plugins:pretix_stamp_rally:booths",
            kwargs={"organizer": self.request.event.organizer.slug, "event": self.request.event.slug},
        )

    @transaction.atomic
    def form_valid(self, form):
        form.instance.event = self.request.event
        if not form.instance.position:
            last = self.request.event.stamp_rally_booths.order_by("-position").first()
            form.instance.position = (last.position + 1) if last else 0
        super().form_valid(form)
        form.instance.log_action(
            "pretix_stamp_rally.booth.added",
            user=self.request.user,
            data=dict(form.cleaned_data),
        )
        messages.success(self.request, _("The booth has been created."))
        return redirect(self.get_success_url())


class BoothUpdateView(EventPermissionRequiredMixin, BoothQueryMixin, UpdateView):
    model = StampRallyBooth
    form_class = BoothForm
    template_name = "pretix_stamp_rally/control_booth_form.html"
    permission = "event.settings.general:write"
    context_object_name = "booth"
    pk_url_kwarg = "booth"

    def get_success_url(self):
        return reverse(
            "plugins:pretix_stamp_rally:booths",
            kwargs={"organizer": self.request.event.organizer.slug, "event": self.request.event.slug},
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["scanner_url"] = eventreverse(
            self.request.event,
            "plugins:pretix_stamp_rally:public.scan",
            kwargs={"token": self.object.scan_token},
        )
        return ctx

    @transaction.atomic
    def form_valid(self, form):
        super().form_valid(form)
        form.instance.log_action(
            "pretix_stamp_rally.booth.changed",
            user=self.request.user,
            data=dict(form.cleaned_data),
        )
        messages.success(self.request, _("Your changes have been saved."))
        return redirect(self.get_success_url())


class BoothDeleteView(EventPermissionRequiredMixin, BoothQueryMixin, CompatDeleteView):
    model = StampRallyBooth
    template_name = "pretix_stamp_rally/control_booth_delete.html"
    permission = "event.settings.general:write"
    context_object_name = "booth"
    pk_url_kwarg = "booth"

    def get_success_url(self):
        return reverse(
            "plugins:pretix_stamp_rally:booths",
            kwargs={"organizer": self.request.event.organizer.slug, "event": self.request.event.slug},
        )

    @transaction.atomic
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.log_action(
            "pretix_stamp_rally.booth.deleted", user=request.user, data={"name": str(self.object.name)}
        )
        self.object.delete()
        messages.success(request, _("The booth has been deleted."))
        return redirect(self.get_success_url())


class BoothTokenResetView(EventPermissionRequiredMixin, BoothQueryMixin, View):
    permission = "event.settings.general:write"

    def post(self, request, *args, **kwargs):
        booth = get_object_or_404(self.get_queryset(), pk=kwargs["booth"])
        booth.regenerate_token()
        booth.log_action("pretix_stamp_rally.booth.token_reset", user=request.user)
        messages.success(request, _("A new scanner link has been created. The old link no longer works."))
        return redirect(
            reverse(
                "plugins:pretix_stamp_rally:booth.edit",
                kwargs={
                    "organizer": request.event.organizer.slug,
                    "event": request.event.slug,
                    "booth": booth.pk,
                },
            )
        )


class SettingsView(EventSettingsViewMixin, EventSettingsFormView):
    model = Event
    form_class = StampRallySettingsForm
    template_name = "pretix_stamp_rally/settings.html"
    permission = "event.settings.general:write"

    def get_success_url(self):
        return reverse(
            "plugins:pretix_stamp_rally:settings",
            kwargs={"organizer": self.request.event.organizer.slug, "event": self.request.event.slug},
        )


class ProgressView(EventPermissionRequiredMixin, ListView):
    permission = "event.orders:read"
    template_name = "pretix_stamp_rally/control_progress.html"
    context_object_name = "entries"
    paginate_by = 50

    def participation_status(self):
        status = self.request.GET.get("status")
        if status is None and self.request.GET.get("complete") == "1":
            status = "complete"
        return normalize_participation_filter(status)

    def get_queryset(self):
        return filter_by_participation(
            progress_queryset(self.request.event),
            self.request.event,
            self.participation_status(),
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        booths = list(active_booths(self.request.event))
        ctx["booths"] = booths
        ctx["required"] = required_stamp_count(self.request.event)
        ctx["status"] = self.participation_status()
        ctx["counts"] = participation_counts(self.request.event)
        for entry in ctx["entries"]:
            info = describe_participation(entry, booths)
            entry.attendee_name_recorded = info["identity"]["name"] or attendee_label(entry)
            entry.attendee_email_recorded = info["identity"]["email"]
            entry.booth_cells = info["cells"]
            entry.collected = info["collected"]
            entry.booth_total = info["total"]
            entry.complete = info["complete"]
        return ctx


class ControlScanView(EventPermissionRequiredMixin, TemplateView):
    permission = "event.orders:checkin"
    template_name = "pretix_stamp_rally/scanner.html"

    @cached_property
    def booth(self):
        return get_object_or_404(self.request.event.stamp_rally_booths.all(), pk=self.kwargs["booth"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["booth"] = self.booth
        ctx["scan_url"] = reverse(
            "plugins:pretix_stamp_rally:booth.scan.api",
            kwargs={
                "organizer": self.request.event.organizer.slug,
                "event": self.request.event.slug,
                "booth": self.booth.pk,
            },
        )
        ctx["is_control"] = True
        return ctx


class ScanAPIMixin:
    def scan_response(self, event, booth, raw_code, user=None):
        if not raw_code:
            return JsonResponse(
                {"status": "invalid", "message": str(_("Please scan a ticket QR code."))},
                status=400,
            )
        result = collect_stamp(event, booth, raw_code)
        if result.status == "ok" and result.position:
            result.position.order.log_action(
                "pretix_stamp_rally.stamp.added",
                user=user,
                data={
                    "booth": booth.pk,
                    "booth_name": str(booth.name),
                    "position": result.position.pk,
                    "positionid": result.position.positionid,
                },
            )
        payload = {
            "status": result.status,
            "message": str(result.message),
            "collected": result.collected,
            "required": result.required,
            "complete": result.complete,
            "booth": result.booth_name,
        }
        if result.position:
            payload["attendee"] = attendee_label(result.position)
            payload["order"] = result.position.order.code
            payload["product"] = str(result.position.item.name)
        status_code = 200 if result.success else 400
        return JsonResponse(payload, status=status_code)


class ControlScanAPIView(EventPermissionRequiredMixin, ScanAPIMixin, View):
    permission = "event.orders:checkin"

    def post(self, request, *args, **kwargs):
        booth = get_object_or_404(request.event.stamp_rally_booths.all(), pk=kwargs["booth"])
        return self.scan_response(request.event, booth, _read_scan_code(request), user=request.user)


class PublicScannerView(TemplateView):
    template_name = "pretix_stamp_rally/scanner.html"

    @cached_property
    def booth(self):
        booth = StampRallyBooth.objects.filter(event=self.request.event, scan_token=self.kwargs["token"]).first()
        if not booth:
            raise Http404()
        return booth

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["booth"] = self.booth
        ctx["scan_url"] = eventreverse(
            self.request.event,
            "plugins:pretix_stamp_rally:public.scan.api",
            kwargs={"token": self.booth.scan_token},
        )
        ctx["is_control"] = False
        return ctx


class RaffleView(EventPermissionRequiredMixin, TemplateView):
    permission = "event.orders:read"
    template_name = "pretix_stamp_rally/control_raffle.html"

    def can_draw(self):
        return self.request.user.has_event_permission(
            self.request.organizer, self.request.event, "event.orders:write", request=self.request
        )

    def get_form(self):
        if self.request.method == "POST":
            return RaffleDrawForm(self.request.POST)
        return RaffleDrawForm()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form"] = kwargs.get("form") or self.get_form()
        ctx["can_draw"] = self.can_draw()
        ctx["pools"] = raffle_pool_counts(self.request.event)
        ctx["draws"] = (
            self.request.event.stamp_rally_draws.select_related("user").prefetch_related("winners").all()
        )
        return ctx

    def post(self, request, *args, **kwargs):
        if not self.can_draw():
            raise PermissionDenied()
        form = RaffleDrawForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        try:
            draw = draw_raffle(
                request.event,
                pool=form.cleaned_data["pool"],
                winner_count=form.cleaned_data["winner_count"],
                exclude_previous=form.cleaned_data["exclude_previous"],
                user=request.user,
                title=form.cleaned_data["title"],
            )
        except RaffleError as exc:
            form.add_error(None, str(exc))
            return self.render_to_response(self.get_context_data(form=form))
        messages.success(request, _("Winners have been drawn."))
        return redirect(
            reverse(
                "plugins:pretix_stamp_rally:raffle",
                kwargs={"organizer": request.event.organizer.slug, "event": request.event.slug},
            )
            + f"#draw-{draw.pk}"
        )


class RaffleStageView(EventPermissionRequiredMixin, TemplateView):
    permission = "event.orders:write"
    template_name = "pretix_stamp_rally/raffle_stage.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["spin_url"] = reverse(
            "plugins:pretix_stamp_rally:raffle.spin",
            kwargs={
                "organizer": self.request.event.organizer.slug,
                "event": self.request.event.slug,
            },
        )
        ctx["back_url"] = reverse(
            "plugins:pretix_stamp_rally:raffle",
            kwargs={
                "organizer": self.request.event.organizer.slug,
                "event": self.request.event.slug,
            },
        )
        ctx["recent_winners"] = (
            StampRallyWinner.objects.filter(draw__event=self.request.event).select_related("draw").order_by("-id")[:20]
        )
        return ctx


class RaffleSpinAPIView(EventPermissionRequiredMixin, View):
    permission = "event.orders:write"

    def post(self, request, *args, **kwargs):
        payload = {}
        if request.content_type and "json" in request.content_type:
            try:
                payload = json.loads(request.body.decode() or "{}")
            except ValueError:
                payload = {}
        else:
            payload = request.POST
        try:
            result = spin_raffle(
                request.event,
                pool=payload.get("pool") or "complete",
                user=request.user,
                title=payload.get("title") or "",
            )
        except RaffleError as exc:
            return JsonResponse({"status": "error", "message": str(exc)}, status=400)
        result["status"] = "ok"
        return JsonResponse(result)


class RaffleVoidView(EventPermissionRequiredMixin, TemplateView):
    permission = "event.orders:write"
    template_name = "pretix_stamp_rally/control_raffle_void.html"

    def get_draw(self):
        return get_object_or_404(self.request.event.stamp_rally_draws.all(), pk=self.kwargs["draw"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["draw"] = self.get_draw()
        return ctx

    def post(self, request, *args, **kwargs):
        draw = self.get_draw()
        void_raffle(draw, request.user)
        messages.success(request, _("The raffle draw has been voided. Those tickets can be drawn again."))
        return redirect(
            reverse(
                "plugins:pretix_stamp_rally:raffle",
                kwargs={"organizer": request.event.organizer.slug, "event": request.event.slug},
            )
        )


class RaffleExportView(EventPermissionRequiredMixin, View):
    permission = "event.orders:read"

    def get(self, request, *args, **kwargs):
        draw = get_object_or_404(
            StampRallyDraw.objects.filter(event=request.event).prefetch_related("winners"),
            pk=kwargs["draw"],
        )
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        filename = f"stamp-rally-raffle-{request.event.slug}-{draw.pk}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(
            [
                gettext_now("Place"),
                gettext_now("Prize"),
                gettext_now("Order code"),
                gettext_now("Position"),
                gettext_now("Attendee name"),
                gettext_now("Attendee email"),
                gettext_now("Booths scanned"),
                gettext_now("Active booths"),
            ]
        )
        for winner in draw.winners.all():
            writer.writerow(
                [
                    winner.place,
                    draw.title,
                    winner.order_code,
                    winner.positionid,
                    winner.attendee_name,
                    winner.attendee_email,
                    winner.booths_scanned,
                    winner.booths_total,
                ]
            )
        return response


class PublicScanAPIView(ScanAPIMixin, View):
    def post(self, request, *args, **kwargs):
        booth = StampRallyBooth.objects.filter(event=request.event, scan_token=kwargs["token"]).first()
        if not booth:
            raise Http404()
        return self.scan_response(request.event, booth, _read_scan_code(request))
