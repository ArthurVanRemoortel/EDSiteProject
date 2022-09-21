import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "EDSiteProject.settings")
django.setup()

from EDSite.tools.data_listener import LiveListener

from EDSite.tools.ed_data import EDData
from EDSite.models import Station, LiveListing


def main():
    ed_data: EDData = EDData()
    ed_data.start_live_listener()


if __name__ == "__main__":
    # Station.objects.filter(tradedangerous_id=None).delete()
    main()
