import gc
import linecache
import os
import time
import tracemalloc
from datetime import datetime, timezone, timedelta
from pprint import pprint
from typing import Any

import django
from django.core.paginator import Paginator
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
    display_top_memory, queryset_iterator, chunked_queryset

from EDSite.models import System, Station, Commodity, Rare, CommodityCategory, LiveListing, HistoricListing
from django.core.cache import cache


class EDData(metaclass=SingletonMeta):
    td_database_status: EDDatabaseState = EDDatabaseState.UNKNOWN

    def __init__(self) -> None:
        self.last_update = make_timezone_aware(datetime.now() - timedelta(days=4))
        # self.redis = redis.Redis(host='localhost', port=6379, db=0)

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
        print("Updating data...")
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
            if not station:
                station = Station(
                    tradedangerous_id=td_station.ID,
                    name=td_station.dbname,
                    ls_from_star=td_station.lsFromStar,
                    pad_size=td_station.maxPadSize,
                    item_count=td_station.itemCount,
                    data_age_days=td_station.dataAge if td_station.dataAge else -1,
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
                    if station.item_count != td_station.itemCount or (td_station.dataAge and abs(
                            station.data_age_days - td_station.dataAge) < 0.1 ):
                        station.item_count = td_station.itemCount
                        station.data_age_days = td_station.dataAge if td_station.dataAge else -1
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
            Station.objects.bulk_update(updated_stations, ['item_count', 'data_age_days', 'black_market', 'ls_from_star', 'market', 'system_id'], batch_size=10000)
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
            if not Rare.objects.filter(tradedangerous_id=td_rare.ID).exists():
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

    def update_local_listings(self, tdb=None, full_update=True):
        changeable_attributes = ['demand_price', 'demand_units', 'demand_level', 'supply_price', 'supply_units',
                                 'supply_level', 'modified']
        if not tdb:
            tdb = self.tdb
        # TODO: Uses 3GB RAM. Split in multiple parts.
        if full_update:
            td_item_station_query = list(tdb.cur.execute(
                """
                    SELECT *
                    FROM  StationItem
                """
            ))
        else:
            td_item_station_query = list(tdb.cur.execute(
                """
                    SELECT *
                    FROM  StationItem WHERE from_live = 1
                """
            ))
        stations: {int: Station} = {station.tradedangerous_id: station for station in Station.objects.filter(~Q(item_count=0)).only('id', 'pad_size', 'fleet', 'tradedangerous_id').all().iterator()}
        commodities_td_to_django_ids: {int: int} = {commodity.tradedangerous_id: commodity.id for commodity in
                                                    Commodity.objects.only('id', 'tradedangerous_id').all().iterator()}
        total_td_listings: int = len(td_item_station_query)
        existing_live_listings = {}
        print('starting LL query...')
        t0 = time.time()
        paginator = Paginator(LiveListing.objects.only('station_id', 'commodity_id',
                                                        'modified').all(), 1000000)
        for i in range(1, paginator.num_pages+1):
            print("Chunk", i)
            # django.db.reset_queries()
            for ll in paginator.page(i).object_list:
                existing_live_listings[(ll.station_id, ll.commodity_id)] = ll
        print(f'Queried LiveListing in {time.time() - t0} seconds.')

        # for i, ll in enumerate(LiveListing.objects.only('station_id', 'commodity_id',
        #                                                 'modified').iterator()):
        #     if i % 10000 == 0:
        #         django.db.reset_queries()
        #     existing_live_listings[(ll.station_id, ll.commodity_id)] = ll

        new_listings = []
        total_new_listings = 0
        new_historic_listings = []
        total_new_historic_listings = 0
        ignored_historic_listings = 0
        updated_listings = []
        total_updated_listings = 0

        for i, td_item_station_row in enumerate(tqdm(td_item_station_query)):
            station_td_id, item_td_id, demand_price, demand_units, demand_level, supply_price, supply_units, supply_level, modified_str, from_live = td_item_station_row
            modified = make_timezone_aware(datetime.strptime(modified_str, "%Y-%m-%d %H:%M:%S"))
            try:
                station: Station = stations[station_td_id]
            except KeyError:
                # Station does not exist in db.
                # print(f"Station TD id {station_td_id} does not exist in django database.")
                station = None
            if station and not station.fleet:
                station_id = station.id
                com_id = commodities_td_to_django_ids[item_td_id]
                try:
                    existing_live_listing = existing_live_listings[(station_id, com_id)]
                    if modified != existing_live_listing.modified:
                        # existing_live_listing: LiveListing = LiveListing.objects.get(station_id=station_id,
                        #                                                              commodity_id=com_id)
                        if (difference_percent(existing_live_listing.demand_price, demand_price) > 10
                                or difference_percent(existing_live_listing.supply_price, supply_price) > 10):
                            new_historic_listings.append(HistoricListing.from_live(existing_live_listing))
                            total_new_historic_listings += 1
                        else:
                            ignored_historic_listings += 1
                        existing_live_listing.demand_price = demand_price
                        existing_live_listing.demand_units = demand_units
                        existing_live_listing.demand_level = demand_level
                        existing_live_listing.supply_price = supply_price
                        existing_live_listing.supply_units = supply_units
                        existing_live_listing.supply_level = supply_level
                        existing_live_listing.modified = modified
                        updated_listings.append(existing_live_listing)
                        total_updated_listings += 1
                except KeyError:
                    # live_listing_date = None
                    live_listing = LiveListing(
                        commodity_id=com_id,
                        station_id=station_id,
                        demand_price=demand_price,
                        demand_units=demand_units,
                        demand_level=demand_level,
                        supply_price=supply_price,
                        supply_units=supply_units,
                        supply_level=supply_level,
                        modified=modified,
                        from_live=from_live
                    )
                    new_listings.append(live_listing)
                    total_new_listings += 1
            else:
                # Special case for fleet carriers.
                ...

            if (i > 0 and i % 1000000 == 0) or i == total_td_listings-1:
                if i == total_td_listings-1:
                    print("This is the last iteration at", i)
                print(f"Intermediate save: New {len(new_listings)}, {len(updated_listings)}, {len(new_historic_listings)}, {ignored_historic_listings}")
                if len(new_listings) > 1000:
                    LiveListing.objects.bulk_create(new_listings, batch_size=10000)
                    new_listings = []
                if len(new_historic_listings) > 1000:
                    HistoricListing.objects.bulk_create(new_historic_listings, batch_size=10000)
                    new_historic_listings = []
                if len(updated_listings) > 1000:
                    LiveListing.objects.bulk_update(updated_listings, changeable_attributes, batch_size=10000)
        print(f"Done updating listings. {total_new_listings} new, {total_updated_listings} updated, {total_new_historic_listings} historic added, {ignored_historic_listings} historic ignored.")

    def update_cache(self):
        t0 = time.time()
        commodities = Commodity.objects.all()
        best_buys = {commodity.id: None for commodity in commodities}
        best_sells = {commodity.id: None for commodity in commodities}
        live_listing: LiveListing
        for live_listing in tqdm(LiveListing.objects.filter(Q(supply_level__gt=0) | Q(demand_level__gt=0)).iterator()):
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
        t0 = time.time()
        tdb = self.tdb
        if data:
            t1 = time.time()
            self.update_tradedangerous_database()
            print(f"Updating TradeDangerous took {time.time() - t1} seconds")
        if update_systems:
            t2 = time.time()
            self.update_local_systems(tdb)
            print(f"Updating systems took {time.time() - t2} seconds")
        if update_stations:
            t3 = time.time()
            self.update_local_stations(tdb)
            print(f"Updating stations took {time.time() - t3} seconds")
        if update_commodities:
            t4 = time.time()
            self.update_local_commodities(tdb)
            print(f"Updating commodities took {time.time() - t4} seconds")
        if update_listings:
            t5 = time.time()
            self.update_local_listings(tdb, full_update=full_listings_update)
            print(f"Updating listings took {time.time() - t5} seconds")
        if update_cache:
            t6 = time.time()
            self.update_cache()
            print(f"Updating cache took {time.time() - t6} seconds")
        print(f"Updating entire database took {time.time() - t0} seconds")

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
