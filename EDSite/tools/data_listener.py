import codecs
import csv
import json
import threading
import time
import zlib
from collections import defaultdict, deque, namedtuple
from datetime import datetime
from pprint import pprint
from urllib import request

import zmq
from django.db import transaction
from django.forms import model_to_dict

from EDSite.helpers import make_timezone_aware, difference_percent
from EDSite.models import Commodity, LiveListing, Station, HistoricListing

# WHITELISTED_SOFTWARE = [
#     "E:D Market Connector [Windows]",
#     "E:D Market Connector [Mac OS]",
#     "E:D Market Connector [Linux]",
#     "EDDiscovery",
#     "EDSM",
#     "EDDI",
# ]

ALT_COMMODITY_NAMES = {
}

FAILED_COMMODITIES_LOG = set()


def update_alt_commodity_names():
    edcd_source = 'https://raw.githubusercontent.com/EDCD/FDevIDs/master/commodity.csv'
    edcd_csv = request.urlopen(edcd_source)
    for line in iter(csv.DictReader(codecs.iterdecode(edcd_csv, 'utf-8'))):
        try:
            ALT_COMMODITY_NAMES[line['symbol'].lower()] = line['name'].lower().replace(' ', '').replace('-', '')
        except KeyError as e:
            ...

update_alt_commodity_names()
# with open('EDSite/tools/commodity.csv', newline='') as csvfile:
#     edcd_dict = csv.DictReader(csvfile, 'utf-8')
#
#     for line in edcd_dict:
#         try:
#             ALT_COMMODITY_NAMES[line['t'].lower()] = line['-'].lower().replace(' ', '').replace('-', '')
#         except KeyError:
#             ...


class MarketPriceEntry(namedtuple('MarketPriceEntry', [
    'system',
    'station',
    'commodities',
    'timestamp',
    'uploader',
    'software',
    'version',
])):
    pass


class LiveListener:
    uri = 'tcp://eddn.edcd.io:9500'
    supportedSchema = 'https://eddn.edcd.io/schemas/commodity/3'


    def __init__(
            self,
            ed_data: 'EDData',
            zmqContext=None,
            minBatchTime=36.,  # seconds
            maxBatchTime=60.,  # seconds
            reconnectTimeout=30.,  # seconds
            burstLimit=500,
    ):

        self.ed_data: 'EDData' = ed_data
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
        self.commodity_names = {c.name.lower().replace(' ', '').replace('-', ''): c for c in Commodity.objects.only('name').all()}
        # self.commodity_names = {c.name.lower().replace(' ', ''): c for c in Commodity.objects.only('name').all()}
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
        to_update_listings = []
        to_update_stations = []
        new_stations = []
        new_listings = []
        new_historic_listings = []
        # carriers_of_interest = self.ed_data.get_carriers_of_interest() # TODO: Update this regularly.
        while self.active:
            if self.paused:
                time.sleep(1)
                continue
            if len(self.data_queue) > 5:
                print(f'WARNING: {len(self.data_queue)} items on queue.')
            if to_update_listings:
                t0 = time.time()
                # print(f"Should update {len(to_update_listings)} live_listings")
                with transaction.atomic():
                    for ll in to_update_listings:
                        # LiveListing.objects.filter(id=ll.id).update(['demand_price', 'demand_units', 'supply_price', 'supply_units', 'modified', 'from_live'])
                        existing_ll = LiveListing.objects.select_for_update().filter(id=ll.id)
                        existing_ll.update(**{key: value for key, value in model_to_dict(ll).items() if key in ['demand_price', 'demand_units', 'supply_price', 'supply_units', 'modified', 'from_live']})
                # print(f"Took {time.time() - t0}")
                to_update_listings = []
            if new_listings:
                t0 = time.time()
                # print(f"Should create {len(new_listings)} new live_listings")
                LiveListing.objects.bulk_create(new_listings)
                # print(f"Took {time.time() - t0}")
                new_listings = []
            if to_update_stations:
                with transaction.atomic():
                    for station in to_update_stations:
                        Station.objects.filter(id=station.id).update(system_id=station.system_id)
                # Station.objects.bulk_update(list(to_update_stations), ['system_id'])
                # print(f"Took {time.time() - t0}")
                # print(f"Updated {len(to_update_stations)} stations.")
                to_update_stations = []
            if new_historic_listings:
                HistoricListing.objects.bulk_create(new_historic_listings)

            try:
                entry = self.data_queue.popleft()
            except IndexError:
                time.sleep(1)
                continue
            # print('-------------------------------------------------')
            # Get the station_is using the system and station names.
            system_name = entry.system.lower()
            station_name = entry.station.lower()
            software = entry.software
            # if software not in WHITELISTED_SOFTWARE:
            #     print(f"Software: {software} ignored")
            #     continue
            # And the software version used to upload the schema.
            try:
                modified = entry.timestamp.replace('T', ' ').replace('Z', '')
                modified = make_timezone_aware(datetime.strptime(modified, "%Y-%m-%d %H:%M:%S"))
            except:
                continue
            commodities = entry.commodities
            if not commodities:
                continue
            station: Station = self.ed_data.station_names_dict.get((station_name, system_name))
            if not station and len(station_name) == 7 and station_name[3] == '-':
                # print("Looking for station ignoring system")
                for station_key, value in self.ed_data.station_names_dict.items():
                    if station_key[0] == station_name:
                        station = self.ed_data.station_names_dict.get(station_key)
                        system = self.ed_data.system_names.get(system_name)
                        if system:
                            station.system_id = system.id
                            to_update_stations.append(station),# tOFO
                            print(f'Changed the station {station} to system {system}')
                        else:
                            pass
                            # TODO: New systems not in db yet.
                        break
            if station:
                station_listings = {listing.commodity_id: listing for listing in LiveListing.objects.filter(station_tradedangerous_id=station.tradedangerous_id)}
                for commodity_entry in commodities:
                    commodity_name = commodity_entry['name'].lower()
                    if (commodity_entry['sellPrice'] == 0 and commodity_entry['buyPrice'] == 0) or (commodity_entry['demand'] == 0 and commodity_entry['stock'] == 0):
                        continue
                    commodity: Commodity = self.commodity_names.get(commodity_name)
                    if not commodity:
                        commodity = self.commodity_names.get(ALT_COMMODITY_NAMES.get(commodity_name))
                        if not commodity:
                            fixed_name = ALT_COMMODITY_NAMES.get(commodity_name)
                            if fixed_name:
                                fixed_name += 's'
                            commodity = self.commodity_names.get(fixed_name)
                    if commodity:
                        live_listings: LiveListing = station_listings.get(commodity.id)
                        demand_price = commodity_entry['sellPrice']
                        supply_price = commodity_entry['buyPrice']
                        demand_units = commodity_entry['demand']
                        supply_units = commodity_entry['stock']
                        if live_listings:
                            live_listings.demand_price = demand_price
                            live_listings.supply_price = supply_price
                            live_listings.demand_units = demand_units
                            live_listings.supply_units = supply_units
                            live_listings.modified = modified
                            live_listings.from_live = 1
                            to_update_listings.append(live_listings)
                            if not station.fleet:
                                if (difference_percent(live_listings.demand_price, demand_price) > 10
                                        or difference_percent(live_listings.supply_price, supply_price) > 10):
                                    new_historic_listings.append(HistoricListing.from_live(live_listings))
                        else:
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
                                from_live=1
                            )
                            new_listings.append(live_listing)
                    else:
                        if commodity_name not in FAILED_COMMODITIES_LOG:
                            FAILED_COMMODITIES_LOG.add(commodity_name)
                            print('WARNING: Commodity not found: ', commodity_name)
            else:
                print(f"Station not found: {(station_name, system_name)}")
            # TODO: Delete listings.

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
                        system, station, commodities,
                        timestamp,
                        uploader, software, swVersion,
                    )

                if bursts >= self.burstLimit:
                    softCutoff = min(softCutoff, time.time() + 0.5)

                for entry in batch.values():
                    self.data_queue.append(entry[0])
        self.disconnect()
        print("Listener reporting shutdown.")