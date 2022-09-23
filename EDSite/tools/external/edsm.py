import logging
import os
import requests
import datetime
from pprint import pprint
from django.core.exceptions import ImproperlyConfigured
from EDSite.helpers import make_timezone_aware, capitalize_string

try:
    from EDSite.models import Station, Faction, LocalFaction
except ImproperlyConfigured:
    import django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "EDSiteProject.settings")
    django.setup()
    from EDSite.models import Station, Faction, LocalFaction

from EDSiteProject.settings import EDSM_API_KEY

logger = logging.getLogger(__name__)

STATION_FIELDS = {
    "name": lambda data: capitalize_string(data["name"]),
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

FACTION_FIELDS = {
    "name": lambda data: capitalize_string(data["name"]),
    "allegiance": lambda data: data["allegiance"],
    "government": lambda data: data["government"],
    "is_player": lambda data: data["isPlayer"],
}

LOCAL_FACTION_FIELDS = {
    "states": lambda data: [state['state'] for state in data["activeStates"]],
    "recovering_states": lambda data: [state['state'] for state in data["recoveringStates"]],
    "pending_states": lambda data: [state['state'] for state in data["pendingStates"]],
    "happiness": lambda data: data["happiness"],
    "influence": lambda data: data["influence"],
    "modified": lambda data: make_timezone_aware(datetime.datetime.fromtimestamp(data["lastUpdate"])),
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
        logger.info(
            f"Warning: EDSM could not determine landing pad size for {station_type}. Assuming Large."
        )
        return "L"


def make_get(url, params) -> {}:
    params["apiKey"] = EDSM_API_KEY
    r = requests.get(url=url, params=params)
    return r.json()


def get_station(system_name: str) -> [{}]:
    url = f"https://www.edsm.net/api-system-v1/stations"
    params = {"systemName": system_name}
    system_data = make_get(url=url, params=params)
    stations = []
    if not system_data["stations"]:
        return None
    try:
        for station_data in system_data["stations"]:
            stations.append({field: function(station_data) for field, function in STATION_FIELDS.items()})
    except Exception as e:
        print(f"Error: Could parse create station from data: {e}")
        pprint(system_data)
        raise e
    return stations


def find_station(search_station_name: str, system_name: str) -> {}:
    station_data = get_station(system_name=system_name)
    for station in station_data:
        if station['name'].lower() == search_station_name.lower():
            return station


def find_faction(search_station_name: str, system_name: str) -> {}:
    station_data = get_station(system_name=system_name)
    for station in station_data:
        if station['name'].lower() == search_station_name.lower():
            return station


def get_factions(system_name: str) -> [{}]:
    url = f"https://www.edsm.net/api-system-v1/factions"
    params = {"systemName": system_name}
    system_factions = make_get(url=url, params=params)
    factions = []
    local_factions = []
    if not system_factions["factions"]:
        return None
    try:
        for faction_data in system_factions["factions"]:
            factions.append({field: function(faction_data) for field, function in FACTION_FIELDS.items()})
            local_factions.append({field: function(faction_data) for field, function in LOCAL_FACTION_FIELDS.items()})

    except Exception as e:
        print(f"Error: Could not parse factions from data: {e}")
        pprint(system_factions)
    return factions, local_factions


def create_station_from_data(station_data: {}) -> Station:
    return Station(**station_data)


def create_faction_from_data(faction_data: {}) -> Faction:
    return Faction(**faction_data)


def create_local_faction_from_data(local_faction_data: {}) -> LocalFaction:
    return LocalFaction(**local_faction_data)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv("../../../.env.dev")
    EDSM_API_KEY = os.getenv("EDSM_API_KEY")



    station_name = "Shirley Hub"
    system_name = "Jaroere"

    data = find_station(station_name, system_name)
    if data:
        station = create_station_from_data(data)
        print(station)
    else:
        print(f"Did not find {station_name} in {system_name}")

    factions, local_factions = get_factions(system_name)
    pprint(factions)
    pprint(local_factions)
