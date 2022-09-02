import json
import os
import random
import threading
import time
import zlib
from collections import defaultdict, deque, namedtuple
import datetime
from pprint import pprint
from django.forms.models import model_to_dict

import zmq
from django import db
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from tqdm import tqdm
from tradedangerous import tradedb, commands
from tradedangerous.commands import exceptions as td_exceptions
from tradedangerous.tradedb import System as TDSystem
from tradedangerous.tradedb import Station as TDStation
from tradedangerous.tradedb import Item as TDItem
from tradedangerous.tradedb import RareItem as TDIRareItem
from tradedangerous.tradedb import Category as TDCategory

from EDSite.helpers import SingletonMeta, EDDatabaseState, make_timezone_aware, StationType, difference_percent, \
    display_top_memory, queryset_iterator, chunked_queryset, chunks, chunks_no_overlap, update_item_dict

from EDSite.models import System, Station, Commodity, Rare, CommodityCategory, LiveListing, HistoricListing, \
    CarrierMission
from django.core.cache import cache

from EDSite.tools.data_listener import LiveListener


class EDData(metaclass=SingletonMeta):
    td_database_status: EDDatabaseState = EDDatabaseState.UNKNOWN
    system_names = {}
    station_names_dict = {}
    commodity_names = {}

    def __init__(self) -> None:
        self.last_update = make_timezone_aware(datetime.datetime.now() - datetime.timedelta(days=4))
        # self.commodity_names = {c.name.lower().replace(' ', ''): c for c in Commodity.objects.only('name').all()}
        # self.system_names = {system.name.lower(): system for system in System.objects.all()}
        # self.station_names_dict = {(station.name.lower(), station.system.name.lower()): station for station in Station.objects.select_related('system').all()}
        self.live_listener = None
        # threading.Thread(target=self.update_cache).start()
        print("Created new EDData object.")

    def start_live_listener(self):
        self.live_listener = LiveListener(ed_data=self)
        self.commodity_names = {c.name.lower().replace(' ', ''): c for c in Commodity.objects.only('name').all()}
        self.system_names = {system.name.lower(): system for system in System.objects.all()}
        self.station_names_dict = {(station.name.lower(), station.system.name.lower()): station for station in Station.objects.select_related('system').all()}
        self.live_listener.start_background()


    @property
    def tdb(self, *args) -> tradedb.TradeDB:
        return tradedb.TradeDB(args)

    def check_tradedangerous_db(self):
        tsc = self.tdb.tradingStationCount
        cmdenv = commands.commandenv
        if tsc == 0:
            raise td_exceptions.NoDataError(
                "There is no trading data for ANY station in "
                "the local database. Please enter or import "
                "price data."
            )
        elif tsc == 1:
            raise td_exceptions.NoDataError(
                "The local database only contains trading data "
                "for one station. Please enter or import data "
                "for additional stations."
            )
        elif tsc < 8:
            cmdenv.NOTE(
                "The local database only contains trading data "
                "for {} stations. Please enter or import data "
                "for additional stations.".format(
                    tsc
                )
            )
        else:
            print(tsc, "trading data found.")
        self.tdb.close()
        return tsc if tsc > 0 else None

    def update_tradedangerous_database(self):
        # self.live_listener.pause()
        first_time = False
        try:
            trade_data = self.check_tradedangerous_db()
        except td_exceptions.NoDataError as e:
            print("Running for the first time. This might take a while.")
            trade_data = None
            first_time = True
        self.tdb.close()
        self.td_database_status = EDDatabaseState.UPDATING
        if trade_data is not None:
            print("Updating price data...")
            argv = ["trade.py", "import", "--merge", "-P", "eddblink", "-O", "skipvend"]
        else:
            print("Updating all data. ")
            argv = ["trade.py", "import", "-P", "eddblink", "-O", "skipvend"]
        cmdenv = commands.CommandIndex().parse(argv)
        tdb = tradedb.TradeDB(cmdenv, load=cmdenv.wantsTradeDB)
        try:
            results = cmdenv.run(tdb)
        finally:
            tdb.close()
        if results:
            results.render()

    def get_carriers_of_interest(self) -> {int: Station}:
        mission: CarrierMission
        return {mission.carrier.id: mission.carrier for mission in CarrierMission.objects.all() if mission.carrier}

    def get_stations_of_interest(self) -> {int: Station}:
        mission: CarrierMission
        return {mission.station.id: mission.station for mission in CarrierMission.objects.all() if mission.station}

    def update_local_systems(self, tdb=None):
        if not tdb:
            tdb = self.tdb
        print('Updating systems...')
        new_systems = []
        td_system: TDSystem
        systems = {system.tradedangerous_id: system for system in System.objects.iterator()}
        for td_system in tdb.systems():
            if td_system.ID not in systems:
                system = System(
                    tradedangerous_id=td_system.ID,
                    name=td_system.dbname,
                    pos_x=td_system.posX,
                    pos_y=td_system.posY,
                    pos_z=td_system.posZ,
                )
                new_systems.append(system)
        if new_systems:
            System.objects.bulk_create(new_systems)
            print(f"Found {len(new_systems)} new systems.")

    def update_local_stations(self, tdb=None):
        if not tdb:
            tdb = self.tdb
        print('Updating stations...')
        td_station: TDStation
        new_stations: [Station] = []
        updated_stations: [Station] = []
        systems = {system.tradedangerous_id: system for system in System.objects.all()}
        stations = {station.tradedangerous_id: station for station in Station.objects.all()}
        deleted_stations_ids = []
        td_stations = tdb.stationByID
        for td_station_id, td_station in tqdm(td_stations.items()):
            try:
                station: Station = stations[td_station.ID]
            except KeyError:
                station = None
            if td_station.dataAge:
                modified = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(days=td_station.dataAge)
            else:
                modified = None
            if not station:
                station = Station(
                    tradedangerous_id=td_station.ID,
                    name=td_station.dbname,
                    ls_from_star=td_station.lsFromStar,
                    pad_size=td_station.maxPadSize,
                    item_count=td_station.itemCount,
                    # data_age_days=td_station.dataAge if td_station.dataAge else -1,
                    modified=modified,
                    market=td_station.market == "Y",
                    black_market=td_station.blackMarket == "Y",
                    shipyard=td_station.shipyard == "Y",
                    outfitting=td_station.outfitting == "Y",
                    rearm=td_station.rearm == "Y",
                    refuel=td_station.refuel == "Y",
                    repair=td_station.repair == "Y",
                    planetary=td_station.planetary == "Y",
                    fleet=td_station.fleet == "Y",
                    odyssey=td_station.odyssey == "Y",
                )
                station.system_id = systems[td_station.system.ID].id
                new_stations.append(station)
            else:
                # (station.data_age_days == -1 and td_station.dataAge)
                try:
                    if station.item_count != td_station.itemCount or modified != station.modified:
                        station.item_count = td_station.itemCount
                        station.modified = modified
                        station.system_id = systems[td_station.system.ID].id
                        station.black_market = td_station.blackMarket == "Y"
                        station.ls_from_star = td_station.lsFromStar
                        station.market = td_station.market == "Y"
                        updated_stations.append(station)
                except TypeError as e:
                    raise e
                    updated_stations.append(station)

        for station_tradedangerous_id, station in stations.items():
            if station_tradedangerous_id not in td_stations:
                deleted_stations_ids.append(station.id)

        if new_stations:
            Station.objects.bulk_create(new_stations)
            print(f"Found {len(new_stations)} new stations.")
        if deleted_stations_ids:
            Station.objects.filter(pk__in=deleted_stations_ids).delete()
            print(f"Deleted {len(deleted_stations_ids)} stations.")

        if updated_stations:
            print(f"Trying to update {len(updated_stations)} stations...")
            with transaction.atomic():
                for station in updated_stations:
                    # print(model_to_dict(ll))
                    Station.objects.filter(id=station.id).update(**model_to_dict(station))
            print(f"Updated {len(updated_stations)} stations.")

    def update_local_commodities(self, tdb=None):
        if not tdb:
            tdb = self.tdb
        print('Updating categories...')
        td_category: TDCategory
        for _, td_category in tdb.categories():
            if not CommodityCategory.objects.filter(tradedangerous_id=td_category.ID).exists():
                com_category = CommodityCategory(
                    tradedangerous_id=td_category.ID,
                    name=td_category.dbname
                )
                com_category.save()
                print(f"Adding category: {com_category}")

        print('Updating commodities...')
        td_item: TDItem
        for td_item in tdb.items():
            if not Commodity.objects.filter(tradedangerous_id=td_item.ID).exists():
                commodity = Commodity(
                    tradedangerous_id=td_item.ID,
                    game_id=td_item.fdevID,
                    name=td_item.dbname,
                    category=CommodityCategory.objects.get(tradedangerous_id=td_item.category.ID),
                    average_price=td_item.avgPrice if td_item.avgPrice else -1,
                )
                commodity.save()
                print(f"Adding commodity: {commodity}")

        print('Updating rares...')
        td_rare: TDIRareItem
        for td_rare in tdb.rareItemByID.values():
            if not Rare.objects.filter(name=td_rare.dbname).exists():
                rare = Rare(
                    tradedangerous_id=td_rare.ID,
                    name=td_rare.dbname,
                    category=CommodityCategory.objects.get(tradedangerous_id=td_rare.category.ID),
                    cost=td_rare.costCr,
                    max_alloc=td_rare.maxAlloc,
                    illegal=td_rare.illegal == 'Y',
                    suppressed=td_rare.suppressed == 'Y',
                )
                rare.save()
                print(f"Adding rare: {rare}")

    def update_local_listings2(self, tdb=None, full_update=True):
        changeable_attributes = ['demand_price', 'demand_units', 'supply_price', 'supply_units', 'modified']
        if not tdb:
            tdb = self.tdb
        stations: {int: Station} = {station.tradedangerous_id: station for station in Station.objects.filter(~Q(item_count=0)).only('id', 'pad_size', 'fleet', 'tradedangerous_id').all().iterator()}
        commodities_td_to_django_ids: {int: int} = {commodity.tradedangerous_id: commodity.id for commodity in
                                                    Commodity.objects.only('id', 'tradedangerous_id').all().iterator()}
        carriers_of_interest: {int: Station} = self.get_carriers_of_interest()
        print("Carriers of interest: ", carriers_of_interest)
        print("Starting TD query...")
        t0 = time.time()
        # min_station_id, max_station_id = list(tdb.cur.execute('SELECT (min("station_id"), max("station_id")) FROM StationItem'))
        td_listings_station_ids = sorted([r[0] for r in tdb.cur.execute('SELECT "station_id" FROM StationItem')])
        TD_PART_SIZE = 200000
        print("-----------")
        new_listings = []
        total_new_listings = 0
        new_historic_listings = []
        total_new_historic_listings = 0
        ignored_historic_listings = 0
        updated_listings = []
        total_updated_listings = 0
        total_updated_carriers = 0
        # station_ids_part_start = min_station_id
        for station_ids_chunk in tqdm(chunks_no_overlap(td_listings_station_ids, TD_PART_SIZE)):
            min_station_td_id, max_station_td_id = min(station_ids_chunk), max(station_ids_chunk)
            t1 = time.time()

            if full_update:
                # TODO: Maybe parse from csv file instead.
                td_row_part = list(tdb.cur.execute('SELECT * FROM StationItem WHERE station_id >= ? and station_id <= ? ORDER BY station_id, item_id', [min_station_td_id, max_station_td_id]))
            else:
                td_row_part = list(tdb.cur.execute('SELECT * FROM StationItem WHERE from_live = 1 and station_id >= ? and station_id <= ? ORDER BY station_id, item_id', [min_station_td_id, max_station_td_id]))


            existing_live_listings = {(ll.station_id, ll.commodity_id): ll for ll in LiveListing.objects.filter(Q(station_tradedangerous_id__gte=min_station_td_id) & Q(station_tradedangerous_id__lte=max_station_td_id)).all()}  # Problem
            db.reset_queries()
            for td_item_station_row in td_row_part:
                station_td_id, item_td_id, demand_price, demand_units, _, supply_price, supply_units, _, modified_str, from_live = td_item_station_row
                modified = make_timezone_aware(datetime.datetime.strptime(modified_str, "%Y-%m-%d %H:%M:%S"))
                try:
                    station: Station = stations[station_td_id]
                except KeyError:
                    # Station does not exist in db.
                    # print(f"Station TD id {station_td_id} does not exist in django database.")
                    station = None
                if station:
                    # if station.fleet and station.id not in carriers_of_interest:
                    #     continue
                    # if station.fleet:
                    #     total_updated_carriers += 1
                    station_id = station.id
                    com_id = commodities_td_to_django_ids[item_td_id]
                    try:
                        existing_live_listing = existing_live_listings[(station_id, com_id)]
                        if modified != existing_live_listing.modified:
                            if not station.fleet:
                                if (difference_percent(existing_live_listing.demand_price, demand_price) > 10
                                        or difference_percent(existing_live_listing.supply_price, supply_price) > 10):
                                    new_historic_listings.append(HistoricListing.from_live(existing_live_listing))
                                    total_new_historic_listings += 1
                                else:
                                    ignored_historic_listings += 1
                            existing_live_listing.demand_price = demand_price
                            existing_live_listing.demand_units = demand_units
                            # existing_live_listing.demand_level = demand_level
                            existing_live_listing.supply_price = supply_price
                            existing_live_listing.supply_units = supply_units
                            # existing_live_listing.supply_level = supply_level
                            existing_live_listing.modified = modified
                            updated_listings.append(existing_live_listing)
                            total_updated_listings += 1
                    except KeyError as e:
                        live_listing = LiveListing(
                            commodity_id=com_id,
                            commodity_tradedangerous_id=item_td_id,
                            station_id=station_id,
                            station_tradedangerous_id=station_td_id,
                            demand_price=demand_price,
                            demand_units=demand_units,
                            # demand_level=demand_level,
                            supply_price=supply_price,
                            supply_units=supply_units,
                            # supply_level=supply_level,
                            modified=modified,
                            from_live=from_live
                        )
                        new_listings.append(live_listing)
                        total_new_listings += 1
                else:
                    # Station not found.
                    ...
        print(f"New {len(new_listings)}, {len(updated_listings)}, {len(new_historic_listings)}, {ignored_historic_listings}")
        if new_listings:
            print("Saving new listings")
            t0 = time.time()
            for chunk in tqdm(list(chunks(new_listings, 200000))):
                # LiveListing.objects.bulk_update_or_create(
                #     chunk,
                #     changeable_attributes + ['commodity_id', 'commodity_tradedangerous_id', 'station_id', 'station_tradedangerous_id', 'from_live'],
                #     match_field=('commodity_id', 'station_id'))
                LiveListing.objects.bulk_create(list(chunk))
            print(f"Saving new took {time.time() - t0}")
        db.reset_queries()
        del new_listings

        if new_historic_listings:
            print("Saving new historic listings")
            for chunk in tqdm(list(chunks(new_historic_listings, 200000))):
                HistoricListing.objects.bulk_create(list(chunk))
                db.reset_queries()
        del new_historic_listings

        t0 = time.time()
        if updated_listings:
            print("Saving updated listings")
            for chunk in tqdm(list(chunks(updated_listings, 20000))):
                # LiveListing.objects.bulk_update(list(chunk), changeable_attributes)
                with transaction.atomic():
                    ll: LiveListing
                    for ll in chunk:
                        # print(model_to_dict(ll))
                        LiveListing.objects.filter(id=ll.id).update(**model_to_dict(ll))  # https://www.sankalpjonna.com/learn-django/running-a-bulk-update-with-django
        db.reset_queries()
        del updated_listings
        print(f"Saving updated listings: {time.time() - t0}")
        print(f"Done updating listings. {total_new_listings} new, {total_updated_listings} updated ({total_updated_carriers} FC listings), {total_new_historic_listings} historic added, {ignored_historic_listings} historic ignored.")

    def update_cache(self):
        commodities = Commodity.objects.all()
        best_buys = {commodity.id: None for commodity in commodities}
        best_sells = {commodity.id: None for commodity in commodities}
        live_listing: LiveListing
        for live_listing in tqdm(LiveListing.objects.filter(Q(supply_units__gte=5) | Q(demand_units__gte=100)).iterator(100000)):
            if live_listing.is_recently_modified:
                if live_listing.is_high_supply() and 0 < live_listing.supply_price and live_listing.is_recently_modified:
                    if not best_sells[live_listing.commodity_id] or best_sells[live_listing.commodity_id].supply_price > live_listing.supply_price:
                        best_sells[live_listing.commodity_id] = live_listing

                if live_listing.is_high_demand() and live_listing.demand_units > 0 and 0 < live_listing.demand_price:
                    if not best_buys[live_listing.commodity_id] or live_listing.demand_price > best_buys[live_listing.commodity_id].demand_price:
                        best_buys[live_listing.commodity_id] = live_listing

        for commodity in commodities:

            if best_buys[commodity.id] and (best_buys[commodity.id].demand_units == 0):
                best_buys[commodity.id] = None
            if best_sells[commodity.id] and best_sells[commodity.id].supply_units == 0:
                best_sells[commodity.id] = None

            if best_buys[commodity.id] or best_sells[commodity.id]:
                cache.set(f'best_{commodity.id}', (best_buys[commodity.id], best_sells[commodity.id]), timeout=None)

    def update_local_database(self, data=True, update_systems=True, update_stations=True, update_commodities=True,
                              update_listings=True, update_cache=True, full_listings_update=True):
        if self.live_listener:
            self.live_listener.pause()
        t0 = time.time()
        tdb = None
        if data:
            tdb = self.tdb
            t1 = time.time()
            self.update_tradedangerous_database()
            print(f"Updating TradeDangerous took {time.time() - t1} seconds")
        if update_systems:
            tdb = self.tdb
            t2 = time.time()
            self.update_local_systems(tdb)
            print(f"Updating systems took {time.time() - t2} seconds")
        if update_stations:
            tdb = self.tdb
            t3 = time.time()
            self.update_local_stations(tdb)
            print(f"Updating stations took {time.time() - t3} seconds")
        if update_commodities:
            tdb = self.tdb
            t4 = time.time()
            self.update_local_commodities(tdb)
            print(f"Updating commodities took {time.time() - t4} seconds")
        if update_listings:
            tdb = self.tdb
            t5 = time.time()
            self.update_local_listings2(tdb, full_update=full_listings_update)
            # self.update_local_listings(tdb, full_update=full_listings_update)
            print(f"Updating listings took {time.time() - t5} seconds")
        if update_cache:
            t6 = time.time()
            self.update_cache()
            print(f"Updating cache took {time.time() - t6} seconds")
        print(f"Updating entire database took {time.time() - t0} seconds")
        if self.live_listener:
            self.live_listener.unpause()

    def avg_selling_items(self):
        return self.tdb.getAverageSelling()

    def get_avg_buying_items(self):
        return self.tdb.getAverageBuying()

    # def lookup_item(self, item_name) -> Commodity | None:
    #     td_item = self.tdb.lookupItem(item_name)
    #     if td_item:
    #         return self.tdb.lookupItem(item_name)
    #     else:
    #         return None
    #
    # def get_item(self, item_id) -> Commodity:
    #     return Commodity.objects.get(pk=item_id)
    #
    #
    # def get_categories(self):
    #     return CommodityCategory.objects.all()
    #     # return {
    #     #     category_value.dbname: {item.ID: CommodityWrapper(item) for item in category_value.items} for category_key, category_value in self.tdb.categories()
    #     # }
