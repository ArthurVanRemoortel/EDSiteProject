import os
import requests
import datetime

from pprint import pprint

from django.core.exceptions import ImproperlyConfigured

from EDSite.helpers import make_timezone_aware

# try:
#     from dotenv import load_dotenv
#     load_dotenv('.env.dev')
# except ModuleNotFoundError:
#     pass
#
# HISTORIC_DIFFERENCE_DELTA = 5
#
# HISTORIC_CACHE_TIMEOUT_HOURS = 12
#
# DATABASE_HOST = os.getenv('')
try:
    from EDSite.models import Station
except ImproperlyConfigured:
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "EDSiteProject.settings")
    django.setup()
    from EDSite.models import Station

from EDSiteProject.settings import EDSM_API_KEY

IMPORTANT_STATION_FIELDS = {
    "name": lambda data: data["name"],
    "ls_from_star": lambda data: int(float(data["distanceToArrival"])),
    "pad_size": lambda data: determine_pad_size(data),
    "modified": lambda data: make_timezone_aware(
        datetime.datetime.strptime(data["updateTime"]["market"], "%Y-%m-%d %H:%M:%S")
        if data["updateTime"]["market"]
        else datetime.datetime.strptime(
            data["updateTime"]["information"], "%Y-%m-%d %H:%M:%S"
        )
    ),
    "market": lambda data: data["haveMarket"],
    "black_market": lambda data: "Black Market" in data["otherServices"],
    "shipyard": lambda data: data["haveShipyard"],
    "outfitting": lambda data: data["haveOutfitting"],
    "rearm": lambda data: "Rearm" in data["otherServices"],
    "refuel": lambda data: data["haveOutfitting"],  # Might be incorrect.
    "repair": lambda data: "Repair" in data["otherServices"],
    "planetary": lambda data: data["type"] == "Odyssey Settlement"
    or "Planetary" in data["type"],
    "fleet": lambda data: data["type"] == "Fleet Carrier",
    "odyssey": lambda data: "Odyssey" in data["type"],
}


def determine_pad_size(data) -> str:
    station_type = data["type"]
    if "Outpost" in station_type:
        return "M"
    elif (
        "Settlement" in station_type
        or "Starport" in station_type
        or "Port" in station_type
        or "Fleet Carrier" == station_type
        or "Observatory" in station_type
    ):
        return "L"
    else:
        print(
            f"Warning: EDSM could not determine landing pad size for {station_type}. Assuming Large."
        )
        return "L"


def make_get(url, params) -> {}:
    params["apiKey"] = EDSM_API_KEY
    r = requests.get(url=url, params=params)
    return r.json()


def find_station(search_station_name: str, system_name: str) -> {}:
    url = f"https://www.edsm.net/api-system-v1/stations?systemName={system_name}"
    params = {"systemName": system_name}
    system_data = make_get(url=url, params=params)
    if not system_data["stations"]:
        return None
    try:
        for station_data in system_data["stations"]:
            if station_data["name"].lower() == search_station_name.lower():
                return {
                    field: function(station_data)
                    for field, function in IMPORTANT_STATION_FIELDS.items()
                }
    except Exception as e:
        print("Error: Could not create station from data: ")
        pprint(system_data)
        raise e
    # print(f"Warning: EDSM did not find the station {search_station_name} in {system_name}. This was the data: ")
    # pprint(system_data)
    return None


def create_station_from_data(station_data: {}) -> Station:
    return Station(**station_data)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv("../../../.env.dev")
    EDSM_API_KEY = os.getenv("EDSM_API_KEY")

    station_name = "bengrina's analytics"
    system_name = "hip 75978"

    data = find_station(station_name, system_name)
    if data:
        station = create_station_from_data(data)
        print(station)
    else:
        print(f"Did not find {station_name} in {system_name}")
