from django.utils.translation import gettext_lazy as _

from . import __version__

try:
    from pretix.base.plugins import PLUGIN_LEVEL_EVENT, PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 2025.7 or above to run this plugin!")


class PluginApp(PluginConfig):
    default = True
    name = "pretix_stamp_rally"
    verbose_name = "Stamp rally"
    default_auto_field = "django.db.models.BigAutoField"

    class PretixPluginMeta:
        name = _("Stamp rally")
        author = "ITSIP Travel"
        description = _(
            "Run a stamp rally where each booth scans the attendee’s ticket QR code. "
            "Collect stamps across booths and mark attendees complete when they reach the required number."
        )
        visible = True
        version = __version__
        category = "FEATURE"
        compatibility = "pretix>=2024.4.0"
        level = PLUGIN_LEVEL_EVENT
        settings_links = [
            ((_("Stamp rally"), _("Booths")), "plugins:pretix_stamp_rally:booths", {}),
        ]
        navigation_links = [
            ((_("Stamp rally"), _("Progress")), "plugins:pretix_stamp_rally:progress", {}),
        ]

    def ready(self):
        from . import defaults  # NOQA
        from . import signals  # NOQA
