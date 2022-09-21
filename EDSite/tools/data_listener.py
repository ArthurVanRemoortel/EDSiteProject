import codecs
import csv
import json
import threading
import time
import zlib
from collections import defaultdict, deque, namedtuple
from datetime import datetime
from pprint import pprint
from typing import Optional, Any, Generator, Iterable
from urllib import request

import zmq
from django.db import transaction
from django.db.models import Q
from django.forms import model_to_dict

from EDSite.helpers import make_timezone_aware, difference_percent, is_carrier_name
from EDSite.models import Commodity, LiveListing, Station, HistoricListing, System

import EDSite.tools.external.edsm as edsm
from dataclasses import dataclass, field

ALT_COMMODITY_NAMES = {}

FAILED_COMMODITIES_LOG = set()


class RetryException(Exception):
    pass


def update_alt_commodity_names():
    edcd_source = "https://raw.githubusercontent.com/EDCD/FDevIDs/master/commodity.csv"
    edcd_csv = request.urlopen(edcd_source)
    for line in iter(csv.DictReader(codecs.iterdecode(edcd_csv, "utf-8"))):
        try:
            ALT_COMMODITY_NAMES[line["symbol"].lower()] = (
                line["name"].lower().replace(" ", "").replace("-", "")
            )
        except KeyError as e:
            ...


update_alt_commodity_names()


class MarketPriceEntry(
    namedtuple(
        "MarketPriceEntry",
        [
            "system",
            "station",
            "commodities",
            "timestamp",
            "uploader",
            "software",
            "version",
        ],
    )
):
    pass


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
        print(f"Retrying {self.station_name}...")
        if self.retries <= 0:
            raise RetryException
        existing_station = Station.objects.get(Q(system_id=self.system.id) & Q(name__icontains=self.station_name))
        if not existing_station:
            station = create_station(self.station_name, self.system, self.extra)
            self.retries -= 1
            if not station:
                self.remaining_timeout = self.timeout
                print(
                    f"WARNING: Retried creating {self.station_name} but failed again. {self.retries} retries remaining."
                )
            else:
                self.retries = 0
            return station
        else:
            print(f"WARNING. RetryStation tried to create new station {self.station_name} but it already existed. Ignored it.")
            self.retries = 0
            return existing_station

    def __repr__(self):
        return f"RetryStation: {self.station_name}, retries={self.retries}, remaining_timeout={self.remaining_timeout}"


def create_station(station_name: str, system: System, extra=None) -> Optional[Station]:
    if extra is None:
        extra = {}
    listings = extra.get("listings")
    if is_carrier_name(station_name):
        station = Station(
            name=station_name.upper(),
            ls_from_star=0,  # Assuming 0. Might not be accurate.
            pad_size="L",
            modified=make_timezone_aware(datetime.now()),
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
            print(
                f"Did not find {station_name} in {system}. It might not exist yet on EDSM but it might appear soon. TODO: Try again later"
            )
            return None
    station.system_id = system.id
    station.tradedangerous_id = None
    station.save()
    return station


def create_listings(new_listings: {Station, list[LiveListing]}):
    stations = []
    for station, listings in new_listings.items():
        if station.name == "K7Q-BQL":
            print(
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


class LiveListener:
    uri = "tcp://eddn.edcd.io:9500"
    supportedSchema = "https://eddn.edcd.io/schemas/commodity/3"

    def __init__(
        self,
        ed_data: "EDData",
        zmqContext=None,
        minBatchTime=36.0,  # seconds
        maxBatchTime=60.0,  # seconds
        reconnectTimeout=30.0,  # seconds
        burstLimit=500,
    ):

        self.ed_data: "EDData" = ed_data
        self.last_received = None
        assert burstLimit > 0
        if not zmqContext:
            zmqContext = zmq.Context()
        self.zmqContext = zmqContext
        self.subscriber = None
        self.paused = False
        self.minBatchTime = minBatchTime
        self.maxBatchTime = maxBatchTime
        self.reconnectTimeout = reconnectTimeout
        self.burstLimit = burstLimit
        self.active = False

        self.listener_thread = None
        self.processor_thread = None
        self.commodity_names = {
            c.name.lower().replace(" ", "").replace("-", ""): c
            for c in Commodity.objects.only("name").all()
        }

        self.data_queue = deque()
        self.connect()

    def pause(self):
        print("Pausing the EDDBLink")
        self.paused = True

    def unpause(self):
        print("Un-Pausing the EDDBLink")
        self.paused = False

    def connect(self):
        if self.subscriber:
            self.subscriber.close()
            del self.subscriber
        self.subscriber = newsub = self.zmqContext.socket(zmq.SUB)
        newsub.setsockopt(zmq.SUBSCRIBE, b"")
        newsub.connect(self.uri)
        self.last_received = time.time()

    def disconnect(self):
        del self.subscriber

    def start_background(self):
        print("Starting background listener in background...")
        self.active = True
        self.listener_thread = threading.Thread(target=self.get_batch)
        self.listener_thread.start()
        self.processor_thread = threading.Thread(target=self.process_messages)
        self.processor_thread.start()

    def wait_for_data(self, softCutoff, hardCutoff):
        now = time.time()
        cutoff = min(softCutoff, hardCutoff)
        if self.last_received < now - self.reconnectTimeout:
            self.connect()
            now = time.time()
        nextCutoff = min(now + self.minBatchTime, cutoff)
        if now > nextCutoff:
            return False
        timeout = (nextCutoff - now) * 1000
        events = self.subscriber.poll(timeout=timeout)
        if events == 0:
            return False
        return True

    def process_messages(self):
        to_update_stations: {int: Station} = {}
        new_listings: {Station, [LiveListing]} = {}
        retry_stations: [RetryStation] = []

        while self.active:
            if self.paused:
                time.sleep(1)
                continue

            if len(self.data_queue) > 5:
                print(f"WARNING: {len(self.data_queue)} items on queue.")

            retry_station: RetryStation
            for retry_station in retry_stations:
                print(f"Retry: {retry_station}")
                # TODO: Should not be hardcoded to 1 seconds.
                can_retry = retry_station.reduce_timeout(1.0)
                if can_retry:
                    station: Station = retry_station.retry()
                    if station and "commodities" in retry_station.extra:
                        print(f"Adding listings to RetryStation: {station}")
                        new_listings[station] = retry_station.extra["commodities"]
            retry_stations[:] = [rs for rs in retry_stations if rs.retries > 0]

            if new_listings:
                # print(f"New listings: {len(new_listings)}")
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
                        Station.objects.select_for_update().filter(
                            id=station.id
                        ).update(system_id=station.system_id, modified=station.modified)
                to_update_stations = {}

            try:
                entry = self.data_queue.popleft()
            except IndexError:
                time.sleep(1)
                continue
            # print(entry)
            system_name = entry.system.lower()
            station_name = entry.station.lower()
            software = entry.software

            try:
                timestamp_string = entry.timestamp.replace("T", " ").replace("Z", "")
                if "." in timestamp_string:
                    timestamp_string = timestamp_string.split(".")[0]
                modified = make_timezone_aware(
                    datetime.strptime(timestamp_string, "%Y-%m-%d %H:%M:%S")
                )
            except Exception as e:
                print(f"Warning: Could not parse datetime from entry: {entry}")
                continue
            commodities = entry.commodities
            if not commodities:
                continue
            if station_name == "K7Q-BQL".lower():
                print("RECEIVED: ", station_name, system_name)
            station: Station = self.ed_data.station_names_dict.get(
                (station_name, system_name)
            )
            if not station and is_carrier_name(station_name):
                for station_key, value in self.ed_data.station_names_dict.items():
                    if station_key[0] == station_name:
                        station = self.ed_data.station_names_dict.get(station_key)
                        system = self.ed_data.system_names.get(system_name)
                        if system:
                            station.system_id = system.id
                            to_update_stations[station.id] = station
                        else:
                            pass
                            # TODO: New systems not in db yet.

            if not station:
                print(
                    f"Station not found: {(station_name, system_name)}. Will create a temporary one."
                )
                system = self.ed_data.system_names.get(system_name)
                if not system:
                    print(f"System {system_name} for {station_name} is not known.")
                    continue
                else:
                    try:
                        station = create_station(
                            station_name, system, extra={"listings": commodities}
                        )
                    except Exception as err:
                        print("ERROR create_station:", err)
                    if station:
                        self.ed_data.station_names_dict[
                            (station_name.lower(), system_name.lower())
                        ] = station
                    else:
                        print(f"Added station {station_name} to retry_stations.")
                        retry_stations.append(
                            RetryStation(
                                system=system,
                                station_name=station_name,
                                extra={"listings": commodities},
                            )
                        )

            if station:
                new_listings[station] = []
                for commodity_entry in commodities:
                    commodity_name = commodity_entry["name"].lower()
                    if (
                        commodity_entry["sellPrice"] == 0
                        and commodity_entry["buyPrice"] == 0
                    ) or (
                        commodity_entry["demand"] == 0 and commodity_entry["stock"] == 0
                    ):
                        continue
                    commodity: Commodity = self.commodity_names.get(commodity_name)
                    if not commodity:
                        commodity = self.commodity_names.get(
                            ALT_COMMODITY_NAMES.get(commodity_name)
                        )
                        if not commodity:
                            fixed_name = ALT_COMMODITY_NAMES.get(commodity_name)
                            if fixed_name:
                                fixed_name += "s"
                            commodity = self.commodity_names.get(fixed_name)
                    if commodity:
                        demand_price = commodity_entry["sellPrice"]
                        supply_price = commodity_entry["buyPrice"]
                        demand_units = commodity_entry["demand"]
                        supply_units = commodity_entry["stock"]
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
                        new_listings[station].append(live_listing)
                    else:
                        if commodity_name not in FAILED_COMMODITIES_LOG:
                            FAILED_COMMODITIES_LOG.add(commodity_name)
                            print("WARNING: Commodity not found: ", commodity_name)

    def get_batch(self):
        while self.active:
            now = time.time()
            hardCutoff = now + self.maxBatchTime
            softCutoff = now + self.minBatchTime
            supportedSchema = self.supportedSchema
            sub = self.subscriber
            batch = defaultdict(list)
            if self.wait_for_data(softCutoff, hardCutoff):
                bursts = 0
                for _ in range(self.burstLimit):
                    try:
                        zdata = sub.recv(flags=zmq.NOBLOCK, copy=False)
                    except zmq.error.Again:
                        continue
                    except zmq.error.ZMQError:
                        pass
                    self.last_received = time.time()
                    bursts += 1
                    try:
                        jsdata = zlib.decompress(zdata)
                    except Exception:
                        continue
                    bdata = jsdata.decode()
                    try:
                        data = json.loads(bdata)
                    except ValueError:
                        continue

                    try:
                        schema = data["$schemaRef"]
                        # print('Received schema:', schema)
                    except KeyError:
                        continue
                    if schema != supportedSchema:
                        continue
                    try:
                        header = data["header"]
                        message = data["message"]
                        system = message["systemName"].upper()
                        station = message["stationName"].upper()
                        commodities = message["commodities"]
                        timestamp = message["timestamp"]
                        uploader = header["uploaderID"]
                        software = header["softwareName"]
                        swVersion = header["softwareVersion"]
                    except (KeyError, ValueError):
                        continue

                    timestamp = timestamp.replace("T", " ").replace("+00:00", "")
                    oldEntryList = batch[(system, station)]
                    if oldEntryList:
                        if oldEntryList[0].timestamp > timestamp:
                            continue
                    else:
                        oldEntryList.append(None)

                    oldEntryList[0] = MarketPriceEntry(
                        system,
                        station,
                        commodities,
                        timestamp,
                        uploader,
                        software,
                        swVersion,
                    )

                if bursts >= self.burstLimit:
                    softCutoff = min(softCutoff, time.time() + 0.5)

                for entry in batch.values():
                    self.data_queue.append(entry[0])
        self.disconnect()
        print("Listener reporting shutdown.")
