import json
import os
import random
import threading
import time
import zlib
from collections import defaultdict, deque, namedtuple
import datetime
from pprint import pprint
from typing import Optional

from django.core.exceptions import ImproperlyConfigured
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
from EDSite.helpers import (
    SingletonMeta,
    EDDatabaseState,
    make_timezone_aware,
    StationType,
    difference_percent,
    queryset_iterator,
    chunked_queryset,
    chunks,
    chunks_no_overlap,
    update_item_dict,
)
from EDSite.tools.eddn_listener import EDDNListener
from EDSiteProject import settings

try:
    from EDSite.models import (
        System,
        Station,
        Commodity,
        Rare,
        CommodityCategory,
        LiveListing,
        HistoricListing,
        CarrierMission,
        Faction,
        LocalFaction,
        State,
    )
except ImproperlyConfigured:
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "EDSiteProject.settings")
    django.setup()
    from EDSite.models import (
        System,
        Station,
        Commodity,
        Rare,
        CommodityCategory,
        LiveListing,
        HistoricListing,
        CarrierMission,
    )
from django.core.cache import cache


class EDData(metaclass=SingletonMeta):
    td_database_status: EDDatabaseState = EDDatabaseState.UNKNOWN
    system_names = {}
    station_names_dict = {}
    commodity_names = {}

    def __init__(self) -> None:
        self.last_update = make_timezone_aware(
            datetime.datetime.now() - datetime.timedelta(days=4)
        )
        self.live_listener = None

        self.commodity_names = {
            c.name.lower().replace(" ", "").replace("-", ""): c
            for c in Commodity.objects.only("name").all()
        }
        self.system_names = {
            system.name.lower(): system for system in System.objects.all()
        }
        self.station_names_dict = {
            (station.name.lower(), station.system.name.lower()): station
            for station in Station.objects.select_related("system").all()
        }

        self.states_dict = {state.id: state for state in State.objects.all()}

        self.faction_names_dict = {
            faction.name.lower(): faction for faction in Faction.objects.all()
        }

        self.local_faction_dict = {
            (
                local_faction.system.id,
                local_faction.faction.name.lower(),
            ): local_faction
            for local_faction in LocalFaction.objects.select_related(
                "system", "faction"
            ).all()
        }

        print("Created new EDData object")

    def cache_find_system(self, name: str) -> Optional[System]:
        return self.system_names.get(name.lower())

    def cache_find_state(self, state_id: int) -> Optional[State]:
        return self.states_dict.get(state_id)

    def cache_find_faction(self, name: str) -> Optional[Faction]:
        return self.faction_names_dict.get(name.lower())

    def cache_set_faction(self, faction: Faction):
        self.faction_names_dict[faction.name.lower()] = faction

    def cache_find_local_faction(
        self, system_id: int, faction_name: str
    ) -> Optional[LocalFaction]:
        return self.local_faction_dict.get((system_id, faction_name.lower()))

    def cache_set_local_faction(self, local_faction: LocalFaction):
        self.local_faction_dict[
            (local_faction.system.id, local_faction.faction.name.lower())
        ] = local_faction

    def start_live_listener(self, daemon=True):
        self.live_listener = EDDNListener()
        self.live_listener.start_background(daemon=daemon)

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
                "for additional stations.".format(tsc)
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
        return {
            mission.carrier.id: mission.carrier
            for mission in CarrierMission.objects.all()
            if mission.carrier
        }

    def get_stations_of_interest(self) -> {int: Station}:
        mission: CarrierMission
        return {
            mission.station.id: mission.station
            for mission in CarrierMission.objects.all()
            if mission.station
        }

    def update_local_systems(self, tdb=None):
        if not tdb:
            tdb = self.tdb
        print("Updating systems...")
        new_systems = []
        td_system: TDSystem
        systems = {
            system.tradedangerous_id: system for system in System.objects.iterator()
        }
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
        print("Updating stations...")
        td_station: TDStation
        new_stations: [Station] = []
        updated_stations: [Station] = []
        systems = {system.tradedangerous_id: system for system in System.objects.all()}
        stations = {
            station.tradedangerous_id: station for station in Station.objects.all()
        }
        stations_names_dict = {
            station.name: station for station in Station.objects.filter(Q(fleet=True))
        }
        fixed_stations_ids_dict: {int: int} = {}  # new id -> original id.
        deleted_stations_ids = set()
        carrier_names = {}
        td_stations_rows = sorted(
            list(tdb.cur.execute("SELECT * FROM Station")), key=lambda r: r[0]
        )
        td_stations_ids = set(r[0] for r in td_stations_rows)
        for row in tqdm(td_stations_rows):
            (
                td_station_id,
                name,
                td_system_id,
                ls_from_star,
                black_market,
                pad_size,
                market,
                shipyard,
                modified_str,
                outfitting,
                rearm,
                refuel,
                repair,
                planetary,
                type_id,
            ) = row
            is_fleet = type_id == 24
            is_odyssey = type_id == 25
            modified = make_timezone_aware(
                datetime.datetime.strptime(modified_str, "%Y-%m-%d %H:%M:%S")
            )
            force_update = False
            try:
                station: Station = stations[td_station_id]
            except KeyError:
                # Station not found. Maybe if it's a carrier the ID just changed.
                if is_fleet:
                    try:
                        match_fleet = stations_names_dict[name]
                        if (
                            match_fleet.tradedangerous_id != td_station_id
                            and match_fleet.modified < modified
                        ):
                            original_id = match_fleet.tradedangerous_id
                            print(
                                f"Fixed tradedangerous_id for {match_fleet} from {original_id} to {td_station_id}"
                            )
                            station = match_fleet
                            station.tradedangerous_id = td_station_id
                            fixed_stations_ids_dict[td_station_id] = original_id
                            force_update = True
                        else:
                            # ID was not found but name was. The name was but it was older than the current one.
                            continue
                    except KeyError:
                        # ID was not found and name was not found. Its new.
                        station = None
                else:
                    station = None
            if not station:
                station = Station(
                    tradedangerous_id=td_station_id,
                    name=name,
                    ls_from_star=ls_from_star,
                    pad_size=pad_size,
                    modified=modified,
                    market=market == "Y",
                    black_market=black_market == "Y",
                    shipyard=shipyard == "Y",
                    outfitting=outfitting == "Y",
                    rearm=rearm == "Y",
                    refuel=refuel == "Y",
                    repair=repair == "Y",
                    planetary=planetary == "Y",
                    fleet=is_fleet,
                    odyssey=is_odyssey,
                )
                station.system_id = systems[td_system_id].id
                new_stations.append(station)
                if station.fleet:
                    if station.name not in carrier_names:
                        carrier_names[station.name] = [station]
                    else:
                        carrier_names[station.name].append(station)
            else:
                try:
                    if (
                        force_update
                        or not station.modified
                        or modified
                        and modified > station.modified
                    ):
                        if not modified or not station.modified:
                            modified = None
                        elif modified <= station.modified:
                            continue
                        station.modified = modified
                        station.system_id = systems[td_system_id].id
                        station.black_market = black_market == "Y"
                        station.ls_from_star = ls_from_star
                        station.market = black_market == "Y"
                        updated_stations.append(station)
                except TypeError as e:
                    raise e
                    # updated_stations.append(station)

        #  TODO: Handle listings where station_tradedangerous_id is None

        # Duplicate carrier check:
        for duplicate_carrier_name, carriers in {
            cn: cs for cn, cs in carrier_names.items() if len(cs) > 1
        }.items():
            most_recent_carrier = carriers[0]
            for c in carriers[1:]:
                if c.modified > most_recent_carrier.modified:
                    most_recent_carrier = c

            for bad_carrier in carriers:
                if bad_carrier != most_recent_carrier:
                    new_stations.remove(bad_carrier)

        fixed_stations_ids_originals = fixed_stations_ids_dict.values()
        for station_tradedangerous_id, station in stations.items():
            if (
                station.tradedangerous_id not in fixed_stations_ids_originals
                and station_tradedangerous_id not in td_stations_ids
            ):
                print(f"Deleting a station: {station}")
                deleted_stations_ids.add(station.id)

        if new_stations:
            print(f"Found {len(new_stations)} new stations. Saving...")
            Station.objects.bulk_create(new_stations)

        if deleted_stations_ids:
            with transaction.atomic():
                for station_id in deleted_stations_ids:
                    Station.objects.filter(pk=station_id).delete()

        to_update_listings = {}
        if updated_stations:
            print(f"Trying to update {len(updated_stations)} stations...")
            with transaction.atomic():
                for station in updated_stations:
                    if station.tradedangerous_id in fixed_stations_ids_dict:
                        # print(f"Need to fix listings for {station}")
                        to_update_listings[
                            station.tradedangerous_id
                        ] = fixed_stations_ids_dict[station.tradedangerous_id]
                    Station.objects.filter(id=station.id).update(
                        **model_to_dict(station)
                    )
            print(f"Updated {len(updated_stations)} stations.")

        if to_update_listings:
            with transaction.atomic():
                for station_td_id, old_td_id in to_update_listings.items():
                    # print(f"Updated listings from {old_td_id} -> {station_td_id}")
                    LiveListing.objects.filter(
                        station_tradedangerous_id=old_td_id
                    ).update(station_tradedangerous_id=station_td_id)

    def update_local_commodities(self, tdb=None):
        if not tdb:
            tdb = self.tdb
        print("Updating categories...")
        td_category: TDCategory
        for _, td_category in tdb.categories():
            if not CommodityCategory.objects.filter(
                tradedangerous_id=td_category.ID
            ).exists():
                com_category = CommodityCategory(
                    tradedangerous_id=td_category.ID, name=td_category.dbname
                )
                com_category.save()
                print(f"Adding category: {com_category}")

        print("Updating commodities...")
        td_item: TDItem
        for td_item in tdb.items():
            if not Commodity.objects.filter(tradedangerous_id=td_item.ID).exists():
                commodity = Commodity(
                    tradedangerous_id=td_item.ID,
                    game_id=td_item.fdevID,
                    name=td_item.dbname,
                    category=CommodityCategory.objects.get(
                        tradedangerous_id=td_item.category.ID
                    ),
                    average_price=td_item.avgPrice if td_item.avgPrice else -1,
                )
                commodity.save()
                print(f"Adding commodity: {commodity}")

        print("Updating rares...")
        td_rare: TDIRareItem
        for td_rare in tdb.rareItemByID.values():
            if not Rare.objects.filter(name=td_rare.dbname).exists():
                rare = Rare(
                    tradedangerous_id=td_rare.ID,
                    name=td_rare.dbname,
                    category=CommodityCategory.objects.get(
                        tradedangerous_id=td_rare.category.ID
                    ),
                    cost=td_rare.costCr,
                    max_alloc=td_rare.maxAlloc,
                    illegal=td_rare.illegal == "Y",
                    suppressed=td_rare.suppressed == "Y",
                )
                rare.save()
                print(f"Adding rare: {rare}")

    def update_local_listings2(self, tdb=None, full_update=True):
        changeable_attributes = [
            "demand_price",
            "demand_units",
            "supply_price",
            "supply_units",
            "modified",
        ]
        if not tdb:
            tdb = self.tdb
        stations: {int: Station} = {
            station.tradedangerous_id: station
            for station in Station.objects.only(
                "id", "pad_size", "fleet", "tradedangerous_id"
            )
            .all()
            .iterator()
        }
        commodities_td_to_django_ids: {int: int} = {
            commodity.tradedangerous_id: commodity.id
            for commodity in Commodity.objects.only("id", "tradedangerous_id")
            .all()
            .iterator()
        }
        carriers_of_interest: {int: Station} = self.get_carriers_of_interest()
        print("Carriers of interest: ", carriers_of_interest)
        print("Starting TD query...")
        t0 = time.time()
        # min_station_id, max_station_id = list(tdb.cur.execute('SELECT (min("station_id"), max("station_id")) FROM StationItem'))
        td_listings_station_ids = sorted(
            [r[0] for r in tdb.cur.execute('SELECT "station_id" FROM StationItem')]
        )
        TD_PART_SIZE = 200000
        new_listings = []
        total_new_listings = 0
        new_historic_listings = []
        total_new_historic_listings = 0
        ignored_historic_listings = 0
        updated_listings = []
        total_updated_listings = 0
        total_updated_carriers = 0

        visited_listings = set()
        deleted_listings_ids = []
        # station_ids_part_start = min_station_id
        for station_ids_chunk in tqdm(
            chunks_no_overlap(td_listings_station_ids, TD_PART_SIZE)
        ):
            min_station_td_id, max_station_td_id = min(station_ids_chunk), max(
                station_ids_chunk
            )
            t1 = time.time()

            if full_update:
                # TODO: Maybe parse from csv file instead.
                td_row_part = list(
                    tdb.cur.execute(
                        "SELECT * FROM StationItem WHERE station_id >= ? and station_id <= ? ORDER BY station_id, item_id",
                        [min_station_td_id, max_station_td_id],
                    )
                )
            else:
                td_row_part = list(
                    tdb.cur.execute(
                        "SELECT * FROM StationItem WHERE from_live = 1 and station_id >= ? and station_id <= ? ORDER BY station_id, item_id",
                        [min_station_td_id, max_station_td_id],
                    )
                )

            existing_live_listings = {
                (ll.station_id, ll.commodity_id): ll
                for ll in LiveListing.objects.filter(
                    Q(station_tradedangerous_id__gte=min_station_td_id)
                    & Q(station_tradedangerous_id__lte=max_station_td_id)
                ).all()
            }  # Problem
            db.reset_queries()
            for td_item_station_row in td_row_part:
                (
                    station_td_id,
                    item_td_id,
                    demand_price,
                    demand_units,
                    _,
                    supply_price,
                    supply_units,
                    _,
                    modified_str,
                    from_live,
                ) = td_item_station_row
                modified = make_timezone_aware(
                    datetime.datetime.strptime(modified_str, "%Y-%m-%d %H:%M:%S")
                )
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

                    visited_listings.add((station_id, com_id))

                    try:
                        existing_live_listing = existing_live_listings[
                            (station_id, com_id)
                        ]
                        visited_listings.add(existing_live_listing.id)
                        if modified != existing_live_listing.modified:
                            if not station.fleet:
                                if (
                                    difference_percent(
                                        existing_live_listing.demand_price, demand_price
                                    )
                                    > settings.HISTORIC_DIFFERENCE_DELTA
                                    or difference_percent(
                                        existing_live_listing.supply_price, supply_price
                                    )
                                    > settings.HISTORIC_DIFFERENCE_DELTA
                                ):
                                    new_historic_listings.append(
                                        HistoricListing.from_live(existing_live_listing)
                                    )
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
                            supply_price=supply_price,
                            supply_units=supply_units,
                            modified=modified,
                            from_live=from_live,
                        )
                        new_listings.append(live_listing)
                        total_new_listings += 1
                else:
                    # Station not found.
                    ...

            for (
                existing_listing_key,
                existing_listing,
            ) in existing_live_listings.items():
                if existing_listing_key not in visited_listings:
                    deleted_listings_ids.append(existing_listing.id)

        print(
            f"new={len(new_listings)}, up={len(updated_listings)}, del={len(deleted_listings_ids)}, hist={len(new_historic_listings)}, ignored={ignored_historic_listings}"
        )
        if new_listings:
            print("Saving new listings")
            t0 = time.time()
            for chunk in tqdm(list(chunks(new_listings, 200000))):
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
                        LiveListing.objects.filter(id=ll.id).update(
                            **model_to_dict(ll)
                        )  # https://www.sankalpjonna.com/learn-django/running-a-bulk-update-with-django
        if deleted_listings_ids:
            print(f"Deleting {len(deleted_listings_ids)} listings.")
            for chunk in tqdm(list(chunks(deleted_listings_ids, 10000))):
                LiveListing.objects.filter(pk__in=chunk).delete()

        db.reset_queries()
        del updated_listings
        print(f"Saving updated listings: {time.time() - t0}")
        print(
            f"Done updating listings. {total_new_listings} new, {total_updated_listings} updated ({total_updated_carriers} FC listings), {total_new_historic_listings} historic added, {ignored_historic_listings} historic ignored."
        )

    def update_cache(self):
        commodities = list(Commodity.objects.all())
        best_buys = {commodity.id: None for commodity in commodities}
        best_sells = {commodity.id: None for commodity in commodities}
        lls = LiveListing.objects.filter(
            Q(supply_units__gte=5) | Q(demand_units__gte=100)
        ).iterator(100000)
        live_listing: LiveListing
        for live_listing in tqdm(lls):
            if live_listing.is_recently_modified:
                existing_best_sell = best_sells[live_listing.commodity_id]
                existing_best_buy = best_buys[live_listing.commodity_id]
                if live_listing.is_high_supply() and 0 < live_listing.supply_price:
                    if (
                        not existing_best_sell
                        or existing_best_sell.supply_price > live_listing.supply_price
                    ):
                        if not live_listing.station.station_type == StationType.FLEET:
                            best_sells[live_listing.commodity_id] = live_listing

                if (
                    live_listing.is_high_demand()
                    and live_listing.demand_units > 0
                    and 0 < live_listing.demand_price
                ):
                    if (
                        not existing_best_buy
                        or live_listing.demand_price > existing_best_buy.demand_price
                    ):
                        if not live_listing.station.station_type == StationType.FLEET:
                            best_buys[live_listing.commodity_id] = live_listing

        for commodity in commodities:
            if best_buys[commodity.id] and (best_buys[commodity.id].demand_units == 0):
                best_buys[commodity.id] = None
            if best_sells[commodity.id] and best_sells[commodity.id].supply_units == 0:
                best_sells[commodity.id] = None

            if best_buys[commodity.id] or best_sells[commodity.id]:
                cache.set(
                    f"best_{commodity.id}",
                    (best_buys[commodity.id], best_sells[commodity.id]),
                    timeout=None,
                )

    def update_local_database(
        self,
        data=True,
        update_systems=True,
        update_stations=True,
        update_commodities=True,
        update_listings=True,
        update_cache=True,
        full_listings_update=True,
    ):
        if self.live_listener:
            self.live_listener.pause()
        t0 = time.time()
        tdb = None
        if data:
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


if __name__ == "__main__":
    os.environ.setdefault("TD_EDDB", "../../data")
    EDData().update_tradedangerous_database()
