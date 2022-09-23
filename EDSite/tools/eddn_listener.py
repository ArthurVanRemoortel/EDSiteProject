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
from EDSite.models import Station, LiveListing, System, Commodity, Faction
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
        logger.info(f"Retrying {self.station_name}...")
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
                logger.warning(
                    f"Retried creating {self.station_name} but failed again. {self.retries} retries remaining."
                )
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
                station.modified = make_timezone_aware(datetime.now())
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
            logger.warning(
                f"Did not find {station_name} in {system}. It might not exist yet on EDSM but it might appear soon."
            )
            return None
    station.system_id = system.id
    station.tradedangerous_id = None
    station.save()
    return station


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
        for message in messages:
            header = message["header"]
            data = message["message"]

            uploader = header["uploaderID"]
            software = header["softwareName"]

            system_name = data["systemName"].lower()
            station_name = data["stationName"].lower()
            timestamp = data["timestamp"]
            commodities = data["commodities"]
            modified = self.parse_timestamp(timestamp)
            if not modified:
                continue

            system, station = determine_station_and_system(
                station_name=station_name, system_name=system_name
            )
            if (
                is_carrier_name(station_name)
                and (station and system)
                and (station.system_id != system.id)
            ):
                station.system_id = system.id
                station.modified = modified
                logger.info(f"Moved carrier {station} to {system}")
                to_update_stations[station_name] = station

            if not station:
                logger.warning(
                    f"Station not found: {(station_name, system_name)}. Will create a temporary one."
                )
                if not system:
                    logger.info(
                        f"System {system_name} for {station_name} is not known."
                    )
                    continue
                station = create_station(
                    station_name, system, extra={"listings": commodities}
                )
                if station:
                    ed_data.EDData().station_names_dict[
                        (station_name.lower(), system_name.lower())
                    ] = station
                else:
                    logger.info(f"Added station {station_name} to retry_stations.")
                    self.retry_stations[(system_name, station_name)] = RetryStation(
                        system=system,
                        station_name=station_name,
                        extra={"listings": commodities},
                    )

            if station:
                if station not in new_listings:
                    new_listings[station] = []
                new_listings[station] = self.parse_listings(
                    station, modified, commodities
                )

        retry_station: RetryStation
        for retry_station in self.retry_stations.values():
            can_retry = retry_station.reduce_timeout(time.time() - self.last_batch_time)
            if can_retry:
                station: Station = retry_station.retry()
                if station:
                    logger.info(f"RetryStation succeeded: {station}")
                    ed_data.EDData().station_names_dict[
                        (station.name.lower(), station.system.name.lower())
                    ] = station
                    if "listings" in retry_station.extra:
                        logger.info(f"Adding listings to RetryStation: {station}")
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
            new_listings.clear()
            for updated_station in updated_stations:
                if updated_station.id not in to_update_stations:
                    to_update_stations[updated_station.id] = updated_station
                to_update_stations[
                    updated_station.id
                ].modified = updated_station.modified

        if to_update_stations:
            with transaction.atomic():
                for station in to_update_stations.values():
                    Station.objects.select_for_update().filter(id=station.id).update(
                        system_id=station.system_id, modified=station.modified
                    )
            to_update_stations.clear()


class JournalProcessor(EDDNSchemaProcessor):
    def process(self):
        messages = self.get_message_batch()
        updated_stations = []
        updated_systems = []
        updated_factions = []
        new_factions = {}
        for message in messages:
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
                updated_systems.append(system)
            # TODO: Station population

            # if "SystemFaction" not in data:
            #     logger.error()

            system_faction_name = data["SystemFaction"]["Name"]
            system_faction = ed_data.EDData().cache_find_faction(system_faction_name)
            system_government = ed_data.EDData().cache_find_government(
                data["SystemGovernment"].split("_")[-1][:-1]
            )
            system_allegiance = ed_data.EDData().cache_find_superpower(
                data["SystemAllegiance"]
            )
            if system.allegiance != system_allegiance or system.government != system_government:
                system.allegiance = system_allegiance
                system.government = system_government
                updated_systems.append(system)
            # I think I do not need to check if system_faction exists since I will look for it below.
            if factions:
                for faction_dict in factions:
                    faction_allegiance = ed_data.EDData().cache_find_superpower(
                        faction_dict["Allegiance"]
                    )
                    faction_government = ed_data.EDData().cache_find_government(
                        faction_dict["Government"]
                    )
                    faction_name: str = faction_dict["Name"]
                    faction = ed_data.EDData().cache_find_faction(faction_name)

                    if not faction:
                        # New system faction
                        new_factions[faction_dict["Name"]] = {
                            "name": faction_name,
                            "government": faction_government,
                            "allegiance": faction_allegiance,
                            "system_faction": system
                            if system_faction_name == faction_name
                            else False,
                        }
                    else:
                        if system.controlling_faction != faction:
                            logger.info(f"Updated controlling faction of {system} from {system.controlling_faction} to {faction}")
                            system.controlling_faction = faction
                            updated_systems.append(system)

        if new_factions:
            for faction_data in new_factions.values():
                controls_system = faction_data["system_faction"]
                if ed_data.EDData().cache_find_faction(faction_data["name"]):
                    logger.warning(f'Tried to create a duplicate faction {faction_data["name"]}. Ignoring it.')
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
                if controls_system and controls_system.controlling_faction_id != faction.id:
                    controls_system.controlling_faction = faction
                    updated_systems.append(controls_system)

        if updated_systems:
            with transaction.atomic():
                for system in updated_systems:
                    System.objects.select_for_update().filter(pk=system.id).update(
                        allegiance=system.allegiance, government=system.government, controlling_faction=system.controlling_faction, population=system.population
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
                        print("Disconnect from EDDN (After timeout)")
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
