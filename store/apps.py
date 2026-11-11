from django.apps import AppConfig


class StoreConfig(AppConfig):
    name = 'store'

    def ready(self):
        from . import health  # noqa: F401 — system check রেজিস্টার করা
