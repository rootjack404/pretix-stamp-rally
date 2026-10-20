from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from pretix.base.forms import SettingsForm

from .models import StampRallyBooth
from .services import PARTICIPATION_ALL, PARTICIPATION_COMPLETE, PARTICIPATION_PARTIAL


class StampRallySettingsForm(SettingsForm):
    stamprally_required_count = forms.IntegerField(
        label=_("Booths required to complete the rally"),
        help_text=_(
            "Set 0 to require every active booth. Otherwise attendees complete the rally "
            "after this many different booths have scanned their ticket."
        ),
        min_value=0,
        required=True,
    )
    stamprally_require_paid = forms.BooleanField(
        label=_("Only accept paid tickets"),
        help_text=_("If enabled, unpaid pending orders cannot collect stamps (unless the order is marked valid if pending)."),
        required=False,
    )
    stamprally_show_progress = forms.BooleanField(
        label=_("Show stamp progress on the order page"),
        required=False,
    )

    def clean_stamprally_required_count(self):
        value = self.cleaned_data["stamprally_required_count"]
        if value is None:
            raise ValidationError(_("Please enter a number."))
        return value


class RaffleDrawForm(forms.Form):
    title = forms.CharField(
        label=_("Prize"),
        required=False,
        max_length=190,
        help_text=_("Optional label, for example “Main prize”."),
    )
    pool = forms.ChoiceField(
        label=_("Who can win"),
        choices=(
            (PARTICIPATION_COMPLETE, _("Complete — scanned at every active booth")),
            (PARTICIPATION_ALL, _("Everyone who was scanned at least once")),
            (PARTICIPATION_PARTIAL, _("Partial — missing at least one booth")),
        ),
        initial=PARTICIPATION_COMPLETE,
    )
    winner_count = forms.IntegerField(
        label=_("Number of winners"),
        min_value=1,
        initial=1,
        help_text=_("Each ticket is one entry. A person with two completed tickets can be drawn twice."),
    )
    exclude_previous = forms.BooleanField(
        label=_("Skip tickets that already won"),
        required=False,
        initial=True,
    )


class BoothForm(forms.ModelForm):
    class Meta:
        model = StampRallyBooth
        fields = ("name", "description", "position", "active")
