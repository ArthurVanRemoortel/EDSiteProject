import django
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "EDSiteProject.settings")
django.setup()
from EDSite.tools.ed_data import EDData
import EDSite.models as models


if __name__ == "__main__":
    models.Faction.objects.all().delete()
    # EDData().start_live_listener(daemon=False)
