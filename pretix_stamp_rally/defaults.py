from pretix.base.settings import settings_hierarkey

settings_hierarkey.add_default("stamprally_required_count", 0, int)
settings_hierarkey.add_default("stamprally_require_paid", True, bool)
settings_hierarkey.add_default("stamprally_show_progress", True, bool)
