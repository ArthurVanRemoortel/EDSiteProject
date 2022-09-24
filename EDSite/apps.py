import sys
import threading

from django.apps import AppConfig


class EdsiteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "EDSite"

    def ready(self):
        if "runserver" not in sys.argv:
            return True
        import EDSite.tools.seeders as seeders
        from EDSiteProject import settings
        from EDSite.tools.ed_data import EDData

        seeders.seedAll()

        if settings.LIVE_UPDATER:
            # TODO: Move this.
            print("Starting the live listener.")
            EDData().start_live_listener(daemon=True)
            # threading.Thread(target=EDData().start_live_listener, daemon=True).start()
        else:
            print("Not starting the live listener.")
