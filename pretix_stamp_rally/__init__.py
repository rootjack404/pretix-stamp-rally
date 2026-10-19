__version__ = "1.0.0"


def __getattr__(name):
    if name == "PretixPluginMeta":
        from .apps import PluginApp

        return PluginApp.PretixPluginMeta
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
