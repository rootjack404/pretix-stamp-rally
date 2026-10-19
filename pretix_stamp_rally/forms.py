from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from pretix.base.forms import SettingsForm

from .models import StampRallyBooth


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


class BoothForm(forms.ModelForm):
    class Meta:
        model = StampRallyBooth
        fields = ("name", "description", "position", "active")
