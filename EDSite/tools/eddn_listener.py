import json
import logging
import random
import threading
import time
import zlib
import queue
import datetime
import zmq
import EDSite.tools.ed_data as ed_data
from dataclasses import dataclass, field
from pprint import pprint
from urllib import request
from typing import Optional, Any
from abc import ABC, abstractmethod
from django.db import transaction
from django.db.models import Q
from EDSite.helpers import is_carrier_name, make_timezone_aware, get_alt_commodity_names
from EDSite.models import (
    Station,
    LiveListing,
    System,
    Commodity,
    Faction,
    SystemSecurities,
    Governments,
    Superpowers,
    States,
    LocalFaction,
    FactionHappiness,
)
from EDSite.tools.external import edsm

logger = logging.getLogger(__name__)

EDDN_URI = "tcp://eddn.edcd.io:9500"
EDDN_TIMEOUT = 60000
EDDN_RECONNECT = 10

ALT_COMMODITY_NAMES = get_alt_commodity_names()


@dataclass
class RetryStation:
    system: System
    station_name: str
    extra: {str: Any}
    retries: int = 3
    timeout: float = 30.0
    remaining_timeout: float = field(init=False, default=30)

    def reduce_timeout(self, dt: float) -> bool:
        self.remaining_timeout -= dt
        return self.remaining_timeout <= 0

    def retry(self) -> Optional[Station]:
        if self.retries <= 0:
            raise Exception(
                f"Cannot retry create station {self.station_name} if retries <= 0"
            )
        existing_station = Station.objects.filter(
            Q(system_id=self.system.id) & Q(name__icontains=self.station_name)
        ).first()
        if not existing_station:
            station = create_station(self.station_name, self.system, self.extra)
            self.retries -= 1
            if not station:
                self.remaining_timeout = self.timeout
                if self.retries == 1:
                    self.remaining_timeout *= 2
                # logger.warning(
                #     f"Retried creating {self.station_name} but failed again. {self.retries} retries remaining."
                # )
            else:
                self.retries = 0
            return station
        else:
            logger.error(
                f"RetryStation tried to create new station {self.station_name} but it already existed. Ignored it."
            )
            self.retries = 0
            return existing_station

    def __repr__(self):
        return f"RetryStation: {self.station_name}, retries={self.retries}, remaining_timeout={self.remaining_timeout}"


def determine_station_and_system(
    station_name: str, system_name: str
) -> (System, Station):
    system_name = system_name.lower()
    station_name = station_name.lower()
    system = None
    station: Optional[Station] = None
    if not is_carrier_name(station_name):
        station: Station = ed_data.EDData().station_names_dict.get(
            (station_name, system_name)
        )
        if station:
            system = station.system
        else:
            system = ed_data.EDData().system_names.get(system_name)
    else:
        system = ed_data.EDData().system_names.get(system_name)
        for station_key, value in ed_data.EDData().station_names_dict.items():
            if station_key[0] == station_name:
                station = ed_data.EDData().station_names_dict.get(station_key)
                break
    return system, station


def create_listings(new_listings: {Station, list[LiveListing]}):
    stations = []
    for station, listings in new_listings.items():
        if station.name == "K7Q-BQL":
            logger.info(
                f"Updating station listing of {station}({station.id})({station.tradedangerous_id}) to {len(listings)}"
            )
        station.set_listings(listings)
        # print(f"Creating listings: {station}")
        for new_listing in listings:
            cached_buy, cached_sell = new_listing.cache_if_better()
        if listings and station.modified != listings[0].modified:
            try:
                station.modified = listings[0].modified
            except IndexError:
                station.modified = make_timezone_aware(datetime.datetime.now())
            stations.append(station)
    return stations


def create_station(station_name: str, system: System, extra=None) -> Optional[Station]:
    if extra is None:
        extra = {}
    listings = extra.get("listings")
    if is_carrier_name(station_name):
        station = Station(
            name=station_name.upper(),
            ls_from_star=0,  # Assuming 0. Might not be accurate.
            pad_size="L",
            modified=make_timezone_aware(datetime.datetime.now()),
            market=len(listings) > 0,
            black_market=False,
            shipyard=False,
            outfitting=False,
            rearm=True,
            refuel=True,
            repair=True,
            planetary=False,
            fleet=True,
            odyssey=False,
        )
    else:
        data = edsm.find_station(station_name, system.name)
        if data:
            station = edsm.create_station_from_data(data)
        else:
            # logger.warning(
            #     f"Did not find {station_name} in {system}. It might not exist yet on EDSM but it might appear soon."
            # )
            return None
    logger.info(f"Created station: {station}")
    station.system_id = system.id
    station.tradedangerous_id = None
    # logger.info(f"IGNORED SAVED station {station}")
    station.save()
    return station


def parse_system_security(system_security_string) -> Optional[SystemSecurities]:
    if not system_security_string:
        return None
    if system_security_string:
        if "$GAlAXY_MAP_INFO_state_" in system_security_string:
            system_security_string = system_security_string[23:][:-1]
        else:
            system_security_string = system_security_string[17:][:-1]
        return SystemSecurities.from_string(system_security_string)


def parse_faction_happiness(happiness_string) -> Optional[FactionHappiness]:
    if happiness_string == "":
        return FactionHappiness.HAPPY
    number = int(happiness_string[-2])
    return FactionHappiness(6 - number)


class EDDNSchemaProcessor(ABC):
    max_batch_size = 10
    max_batch_timeout = 10  # Seconds.
    __processor_thread_timout = 1

    def __init__(self):
        self.active = True
        self.message_queue = queue.Queue()
        self.last_batch_time = time.time()
        threading.Thread(target=self.__processor_thread, daemon=True).start()

    def add_message(self, entry):
        self.message_queue.put(entry)

    def __processor_thread(self):
        """
        Thread that calls self.process() if the queue has reached it max size or some time has passed.
        """
        while self.active:
            time.sleep(self.__processor_thread_timout)
            if (time.time() - self.last_batch_time >= self.max_batch_timeout) or (
                self.message_queue.qsize() >= self.max_batch_size
            ):
                self.process()
                self.last_batch_time = time.time()

    @abstractmethod
    def process(self):
        pass

    def get_message_batch(self):
        messages = []
        while not self.message_queue.empty():
            messages.append(self.message_queue.get())
        return messages

    def parse_timestamp(self, timestamp_string: str) -> Optional[datetime.datetime]:
        try:
            timestamp_string = timestamp_string.replace("T", " ").replace("Z", "")
            if "." in timestamp_string:
                timestamp_string = timestamp_string.split(".")[0]
            modified = make_timezone_aware(
                datetime.datetime.strptime(timestamp_string, "%Y-%m-%d %H:%M:%S")
            )
            return modified
        except Exception as e:
            logger.error(f"Could not parse datetime from message: {timestamp_string}")


class CommodityProcessor(EDDNSchemaProcessor):
    max_batch_size = 5
    retry_stations: {str: RetryStation} = {}

    @staticmethod
    def parse_listings(
        station: Station, modified: datetime, listings_data: list[{}]
    ) -> [LiveListing]:
        results = []
        for listing_data in listings_data:
            commodity_name = listing_data["name"].lower()
            demand_price = listing_data["sellPrice"]
            supply_price = listing_data["buyPrice"]
            demand_units = listing_data["demand"]
            supply_units = listing_data["stock"]

            if (demand_price == 0 and supply_price == 0) or (
                demand_units == 0 and supply_units == 0
            ):
                continue

            commodity: Commodity = ed_data.EDData().commodity_names.get(commodity_name)
            if not commodity:
                commodity = ed_data.EDData().commodity_names.get(
                    ALT_COMMODITY_NAMES.get(commodity_name)
                )
                if not commodity:
                    fixed_name = ALT_COMMODITY_NAMES.get(commodity_name)
                    if fixed_name:
                        fixed_name += "s"
                    commodity = ed_data.EDData().commodity_names.get(fixed_name)
            if commodity:
                live_listing = LiveListing(
                    commodity_id=commodity.id,
                    commodity_tradedangerous_id=commodity.tradedangerous_id,
                    station_id=station.id,
                    station_tradedangerous_id=station.tradedangerous_id,
                    demand_price=demand_price,
                    demand_units=demand_units,
                    supply_price=supply_price,
                    supply_units=supply_units,
                    modified=modified,
                    from_live=1,
                )
                results.append(live_listing)
        return results

    def process(self):
        messages = self.get_message_batch()
        to_update_stations: {str, Station} = {}
        new_listings: {Station: list} = {}
        new_stations: {(str, str), {str: Any}} = {}
        for message in messages:
            header = message["header"]
            data = message["message"]

            uploader = header["uploaderID"]
            software = header["softwareName"]

            system_name = data["systemName"]
            station_name = data["stationName"]
            timestamp = data["timestamp"]
            commodities = data["commodities"]
            modified = self.parse_timestamp(timestamp)
            if not modified:
                continue

            system, station = determine_station_and_system(
                station_name=station_name, system_name=system_name
            )

            if station and station.name == "K7Q-BQL":
                logger.info(f"Message about station {station}")

            if not system:
                # logger.warning(f"System {system_name} for {station_name} is not known.")
                continue

            if (
                is_carrier_name(station_name)
                and (station and system)
                and (station.system_id != system.id)
            ):
                logger.info(
                    f"Moved carrier {station} from {station.system} to {system}"
                )
                station.system_id = system.id
                station.modified = modified
                to_update_stations[station.id] = station

            if station:
                # logger.warning(f"{station}, {modified - station.modified}")
                if is_carrier_name(
                    station.name
                ) or modified - station.modified > datetime.timedelta(minutes=4):
                    # Update the listings.
                    if station not in new_listings:
                        new_listings[station] = []
                    new_listings[station] = self.parse_listings(
                        station, modified, commodities
                    )
                    station.modified = modified
                    to_update_stations[station.id] = station

            if not station:
                # It's a new station:
                if (system_name, station_name) not in self.retry_stations:
                    new_stations[(system_name, station_name)] = {
                        "system": system,
                        "station_name": station_name,
                        "modified": modified,
                        "extra": {"listings": commodities},
                    }
                # else:
                #     logger.warning(f"Station {station_name} was already in retry_stations. It has been skipped.")
        for new_station_data in new_stations.values():
            station_name = new_station_data["station_name"]
            system = new_station_data["system"]
            modified = new_station_data["modified"]
            listings = new_station_data["extra"]["listings"]
            # logger.info(
            #     f"Station not found: {(station_name, system.name)}. Will create a temporary one."
            # )
            station = create_station(station_name, system, extra={"listings": listings})
            if station:
                ed_data.EDData().station_names_dict[
                    (station_name.lower(), system.name.lower())
                ] = station
            else:
                # logger.info(f"Added station {station_name} to retry_stations.")
                self.retry_stations[(system.name, station_name)] = RetryStation(
                    system=system,
                    station_name=station_name,
                    extra={"listings": listings},
                )
            if station:
                if station not in new_listings:
                    new_listings[station] = []
                new_listings[station] = self.parse_listings(station, modified, listings)

        retry_station: RetryStation
        for retry_station in self.retry_stations.values():
            can_retry = retry_station.reduce_timeout(time.time() - self.last_batch_time)
            if can_retry:
                station: Station = retry_station.retry()
                if station:
                    # logger.info(f"RetryStation succeeded: {station}")
                    ed_data.EDData().station_names_dict[
                        (station.name.lower(), station.system.name.lower())
                    ] = station
                    if "listings" in retry_station.extra:
                        # logger.info(f"Adding listings to RetryStation: {station}")
                        if station not in new_listings:
                            new_listings[station] = []
                        new_listings[station] = self.parse_listings(
                            station,
                            station.modified,
                            retry_station.extra["listings"],
                        )
        self.retry_stations = {
            key: rs for key, rs in self.retry_stations.items() if rs.retries > 0
        }

        if new_listings:
            updated_stations = create_listings(new_listings)
            # for s in new_listings.keys():
            #     logger.info(f"Updated listings for {s}")
            new_listings.clear()
            # for updated_station in updated_stations:
            #     if (updated_station.system.name, updated_station.name) in new_stations:
            #         # logger.warning(f'Skipped update of station {updated_station} that was just created.')
            #         continue
            #     if updated_station.id not in to_update_stations:
            #         to_update_stations[updated_station.id] = updated_station
            #     to_update_stations[
            #         updated_station.id
            #     ].modified = updated_station.modified

        if to_update_stations:
            with transaction.atomic():
                for station in to_update_stations.values():
                    # logger.info(f"Updated station: {station}")
                    Station.objects.select_for_update().filter(id=station.id).update(
                        system_id=station.system_id, modified=station.modified
                    )
            to_update_stations.clear()


class JournalProcessor(EDDNSchemaProcessor):
    max_batch_size = 20

    def process(self):
        messages = self.get_message_batch()
        updated_stations = []
        updated_systems = []
        updated_factions = []
        new_factions = {}
        new_local_factions = {}
        for message in messages:
            system_changed = False
            header = message["header"]
            data: {} = message["message"]
            uploader = header["uploaderID"]
            software = header["softwareName"]

            timestamp = data["timestamp"]
            modified = self.parse_timestamp(timestamp)
            if not modified:
                continue

            factions = data.get("Factions")
            conflicts = data.get("Conflicts")
            population = data.get("Population")
            body_type = data.get("BodyType")
            system_name = data.get("StarSystem")
            system_security = parse_system_security(data.get("SystemSecurity"))

            system: Optional[System] = ed_data.EDData().cache_find_system(system_name)

            if not system:
                # logger.warning(f"System {system_name} was not found. Population={population}")
                continue

            if body_type not in ["Star", "Station"]:
                continue

            if body_type == "Star" and (population == 0 or population is None):
                logger.warning(
                    f"System {system} has no population. Ignoring it. Verify is this is true."
                )
                continue

            if system.population != population:
                system.population = population
                system_changed = True

            if system.security != system_security:
                system.security = system_security
                system_changed = True

            system_government = Governments.from_string(
                data["SystemGovernment"].split("_")[-1][:-1]
            )
            system_allegiance = Superpowers.from_string(data["SystemAllegiance"])

            system_faction_name = data["SystemFaction"]["Name"]
            # system_faction = ed_data.EDData().cache_find_faction(system_faction_name)

            if (
                system.allegiance != system_allegiance
                or system.government != system_government
            ):
                system.allegiance = system_allegiance
                system.government = system_government
                system_changed = True
            # I think I do not need to check if system_faction exists since I will look for it below.
            if factions:
                for faction_dict in factions:
                    # print(faction_dict)
                    faction_name: str = faction_dict["Name"]

                    faction_allegiance = Superpowers.from_string(
                        faction_dict["Allegiance"]
                    )
                    faction_government = Governments.from_string(
                        faction_dict["Government"]
                    )

                    faction_active_states = [
                        States.from_string(state["State"])
                        for state in faction_dict.get("ActiveStates", [])
                    ]

                    faction_pending_states = [
                        States.from_string(state["State"])
                        for state in faction_dict.get("PendingStates", [])
                    ]
                    faction_recovering_states = [
                        States.from_string(state["State"])
                        for state in faction_dict.get("RecoveringStates", [])
                    ]

                    faction_influence = float(faction_dict.get("Influence"))
                    try:
                        happiness = parse_faction_happiness(
                            faction_dict.get("Happiness")
                        )
                    except Exception as e:
                        # if happiness != '$Faction_HappinessBand2;':
                        logger.info(
                            f'Happiness: {faction_dict.get("Happiness")} for {faction_name} in {system}'
                        )
                        raise e

                    faction = ed_data.EDData().cache_find_faction(faction_name)
                    if not faction:
                        # New system faction
                        new_factions[faction_dict["Name"]] = {
                            "name": faction_name,
                            "system": system,
                            "government": faction_government,
                            "allegiance": faction_allegiance,
                            "system_faction": system
                            if system_faction_name == faction_name
                            else False,
                        }
                    else:
                        if (
                            system_faction_name == faction_name
                            and system.controlling_faction != faction
                        ):
                            # logger.info(f"Updated controlling faction of {system} from {system.controlling_faction} to {faction}")
                            system.controlling_faction = faction
                            system_changed = True

                    new_local_factions[(system.id, faction_name)] = {
                        "name": faction_name,
                        "system": system,
                        "states": faction_active_states,
                        "pending_states": faction_pending_states,
                        "recovering_states": faction_recovering_states,
                        "influence": faction_influence,
                        "happiness": happiness,
                        "modified": modified,
                        # "DEBUG": faction_dict,
                    }

            if system_changed:
                updated_systems.append(system)

        if new_factions:
            for faction_data in new_factions.values():
                controls_system = faction_data["system_faction"]
                if ed_data.EDData().cache_find_faction(faction_data["name"]):
                    logger.warning(
                        f'Tried to create a duplicate faction {faction_data["name"]}. ignored it.'
                    )
                    continue
                faction = Faction(
                    name=faction_data["name"],
                    allegiance=faction_data["allegiance"],
                    government=faction_data["government"],
                    is_player=False,  # TODO: Get this from some API.
                    tradedangerous_id=None,
                )
                faction.save()
                ed_data.EDData().cache_set_faction(faction)
                # logger.info(f'Created new faction: {faction}')
                if (
                    controls_system
                    and controls_system.controlling_faction_id != faction.id
                ):
                    controls_system.controlling_faction = faction
                    updated_systems.append(controls_system)

        if new_local_factions:
            for local_faction_data in new_local_factions.values():
                name: str = local_faction_data["name"]
                system: System = local_faction_data["system"]
                faction = ed_data.EDData().cache_find_faction(name)
                if not faction:
                    logger.error(
                        f"Tried to create LocalFaction for {name} but it did not exist in the database"
                    )
                    continue
                existing_local_faction = ed_data.EDData().cache_find_local_faction(
                    system_id=system.id, faction_name=name
                )
                if not existing_local_faction:
                    local_faction = LocalFaction(
                        faction=faction,
                        system=system,
                        happiness=local_faction_data.get("happiness"),
                        influence=local_faction_data.get("influence"),
                        modified=local_faction_data.get("modified"),
                    )
                    local_faction.save()
                    try:
                        local_faction.states.set(
                            [
                                ed_data.EDData().cache_find_state(s.value)
                                for s in local_faction_data.get("states")
                            ]
                        )
                        local_faction.recovering_states.set(
                            [
                                ed_data.EDData().cache_find_state(s.value)
                                for s in local_faction_data.get("recovering_states")
                            ]
                        )
                        local_faction.pending_states.set(
                            [
                                ed_data.EDData().cache_find_state(s.value)
                                for s in local_faction_data.get("pending_states")
                            ]
                        )
                    except Exception as er:
                        raise er
                    local_faction.save()
                    ed_data.EDData().cache_set_local_faction(local_faction)
                    # logger.info(f"Created local_faction: {local_faction} in {system}")
                else:
                    states_changed = existing_local_faction.has_states_changed(
                        local_faction_data.get("states"),
                        local_faction_data.get("recovering_states"),
                        local_faction_data.get("pending_states"),
                    )
                    other_changed = (
                        existing_local_faction.influence
                        != local_faction_data.get("influence")
                    )
                    # logger.info(f"{existing_local_faction}, {other_changed}, {states_changed}")
                    if (
                        states_changed or other_changed
                    ):  # TODO: Or anything else changed?
                        # logger.warning(f"Trying to update LocalFaction {existing_local_faction} updated in {system} (states_changed={states_changed}, other_changed={other_changed})")
                        with transaction.atomic():
                            l_faction: LocalFaction = (
                                LocalFaction.objects.select_for_update().get(
                                    pk=existing_local_faction.id
                                )
                            )
                            if states_changed:
                                local_faction_data.get("states")
                                local_faction_data.get("recovering_states")
                                local_faction_data.get("pending_states")
                                l_faction.states.set(
                                    [
                                        ed_data.EDData().cache_find_state(s.value)
                                        for s in local_faction_data.get("states")
                                    ]
                                )
                                l_faction.recovering_states.set(
                                    [
                                        ed_data.EDData().cache_find_state(s.value)
                                        for s in local_faction_data.get(
                                            "recovering_states"
                                        )
                                    ]
                                )
                                l_faction.pending_states.set(
                                    [
                                        ed_data.EDData().cache_find_state(s.value)
                                        for s in local_faction_data.get(
                                            "pending_states"
                                        )
                                    ]
                                )
                            if other_changed or states_changed:
                                l_faction.happiness = local_faction_data.get(
                                    "happiness"
                                )
                                l_faction.influence = local_faction_data.get(
                                    "influence"
                                )
                                l_faction.modified = local_faction_data.get("modified")

                            l_faction.save()

                        # logger.warning(
                        #     f"LocalFaction {existing_local_faction} updated in {system} (states_changed={states_changed}, other_changed={other_changed})"
                        # )

        if updated_systems:
            with transaction.atomic():
                for system in updated_systems:
                    # logger.info(f'Updated system: {system}')
                    System.objects.select_for_update().filter(pk=system.id).update(
                        allegiance=system.allegiance,
                        government=system.government,
                        controlling_faction=system.controlling_faction,
                        population=system.population,
                        security=system.security,
                    )
                    # logger.info(f'updated system demographics: {system}')


class EDDNListener:
    context = zmq.Context()
    subscriber = context.socket(zmq.SUB)
    subscriber.setsockopt(zmq.SUBSCRIBE, b"")

    def __init__(self):
        self.paused = False
        self.active = False
        self.listener_thread = None

        self.schema_processors: {str: EDDNSchemaProcessor} = {
            "https://eddn.edcd.io/schemas/commodity/3": CommodityProcessor(),
            "https://eddn.edcd.io/schemas/journal/1": JournalProcessor(),
        }

    def start_listening(self):
        self.active = True
        while self.active:
            try:
                self.subscriber.connect(EDDN_URI)
                poller = zmq.Poller()
                poller.register(self.subscriber, zmq.POLLIN)

                while self.active:
                    if self.paused:
                        time.sleep(1)
                        continue

                    socks = dict(poller.poll(EDDN_TIMEOUT))
                    if socks:
                        if socks.get(self.subscriber) == zmq.POLLIN:
                            message = self.subscriber.recv(zmq.NOBLOCK)
                            message = zlib.decompress(message)
                            message = message.decode()
                            message = json.loads(message)
                            schema = message["$schemaRef"]
                            processor = self.schema_processors.get(schema)
                            if processor:
                                processor.add_message(message)
                    else:
                        logger.error("Disconnect from EDDN (After timeout)")
                        self.subscriber.disconnect(EDDN_URI)
                        break

            except zmq.ZMQError as e:
                logger.warning(f"Disconnect from EDDN (After receiving ZMQError): {e}")
                self.subscriber.disconnect(EDDN_URI)
                logger.warning("Reconnecting to EDDN in %d seconds." % EDDN_RECONNECT)
                time.sleep(EDDN_RECONNECT)
            except Exception as e:
                logger.critical(
                    f"Unhandled exception occurred while processing EDDN messages. {e}"
                )
                break

    def start_background(self, daemon):
        logger.info("Starting EDDN listener.")
        self.listener_thread = threading.Thread(
            target=self.start_listening, daemon=daemon
        )
        self.listener_thread.start()

    def pause(self):
        logger.info("Pausing the EDDBLink")
        self.paused = True

    def unpause(self):
        logger.info("Un-Pausing the EDDBLink")
        self.paused = False
