import django
import os

import tradedangerous
from django.db.models import Q

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "EDSiteProject.settings")
django.setup()
from EDSite.tools.ed_data import EDData
import EDSite.models as models
from django.utils import timezone
from datetime import timedelta

if __name__ == "__main__":
    ...
    # for station in models.Station.objects.filter(modified__gte=timezone.now() - timedelta(days=14)).filter(tradedangerous_id=None).all():
    #     dupe_station = models.Station.objects.filter(~Q(pk=station.id)).filter(name=station.name).first()
    #     if dupe_station:
    #         if dupe_station.modified > station.modified:
    #             station.delete()
    #         else:
    #             dupe_station.delete()

    # models.LocalFaction.objects.all().delete()
    # EDData().start_live_listener(daemon=False)
