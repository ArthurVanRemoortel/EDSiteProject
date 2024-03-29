from django.db import models
from django.db.models import Q
from EDSite.helpers import (
    StationType,
    difference_percent,
    is_listing_better_than,
    datetime_to_age_string,
    ParsableChoices,
)
from django.core.cache import cache
from django.conf import settings
from django.db import transaction
from pprint import pprint
from django.forms.models import model_to_dict
from django.utils import timezone
from enum import Enum, IntEnum
import time
import datetime
from typing import Optional

IS_LIVE_MINUTES = 60


class FactionHappiness(models.IntegerChoices, ParsableChoices):
    DESPONDENT = 1, "Despondent"
    UNHAPPY = 2, "Unhappy"
    DISCONTENTED = 3, "Discontented"
    HAPPY = 4, "Happy"
    ELATED = 5, "Elated"


class SystemSecurities(models.IntegerChoices, ParsableChoices):
    LOW = 1, "Low"
    MEDIUM = 2, "Medium"
    HIGH = 3, "High"
    ANARCHY = 4, "Anarchy"
    LAWLESS = 5, "Lawless"


class States(models.IntegerChoices, ParsableChoices):
    INCURSION = 1, "Incursion"
    INFESTED = 2, "Infested"
    BLIGHT = 3, "Blight"
    DROUGHT = 4, "Drought"
    OUTBREAK = 5, "Outbreak"
    INFRASTRUCTURE_FAILURE = 6, "infrastructure Failure"
    NATURAL_DISASTER = 7, "Natural Disaster"
    REVOLUTION = 8, "Revolution"
    COLD_WAR = 9, "Cold War"
    TRADE_WAR = 10, "Trade War"
    PIRATE_ATTACK = 11, "Pirate Attack"
    TERRORISM = 12, "Terrorism"
    PUBLIC_HOLIDAY = 13, "Public Holiday"
    TECHNOLOGICAL_LEAP = 14, "Technological Leap"
    HISTORIC_EVENT = 15, "Historic Event"
    COLONISATION = 16, "Colonisation"
    WAR = 17, "War"
    CIVIL_WAR = 18, "Civil War"
    ELECTION = 19, "Election"
    RETREAT = 20, "Retreat"
    EXPANSION = 21, "Expansion"
    NONE = 22, "None"

    FAMINE = 101, "Famine"
    BUST = 102, "Bust"
    BOOM = 104, "Boom"
    INVESTMENT = 105, "Investment"

    LOCKDOWN = 201, "Lockdown"
    CIVIL_UNREST = 202, "Civil Unrest"
    CIVIL_LIBERTY = 204, "Civil Liberty"


class Superpowers(models.IntegerChoices, ParsableChoices):
    EMPIRE = 1, "Empire"
    INDEPENDENT = 2, "Independent"
    ALLIANCE = 3, "Alliance"
    FEDERATION = 4, "Federation"


class Governments(models.IntegerChoices, ParsableChoices):
    ANARCHY = 1, "Anarchy"
    COMMUNISM = 2, "Communism"
    CONFEDERACY = 3, "Confederacy"
    COOPERATIVE = 4, "Cooperative"
    CORPORATE = 5, "Corporate"
    DEMOCRACY = 6, "Democracy"
    DICTATORSHIP = 7, "Dictatorship"
    FEUDAL = 8, "Feudal"
    PATRONAGE = 9, "Patronage"
    PRISON_COLONY = 10, "Prison Colony"
    THEOCRACY = 11, "Theocracy"


class CommodityCategory(models.Model):
    name = models.CharField(max_length=100)
    tradedangerous_id = models.IntegerField(unique=True, db_index=True)

    @property
    def sorted_commodities(self):
        return self.commodities.order_by("name")

    @property
    def sorted_profit_commodities(self):
        return sorted(
            list(self.commodities.all()), key=lambda c: c.max_profit, reverse=True
        )

    def __str__(self):
        return self.name


class Commodity(models.Model):
    name = models.CharField(max_length=100)
    category = models.ForeignKey(
        CommodityCategory, on_delete=models.CASCADE, related_name="commodities"
    )
    average_price = models.IntegerField()

    game_id = models.IntegerField(unique=True, db_index=True)
    tradedangerous_id = models.IntegerField(unique=True, db_index=True)

    _best_buy = None
    _best_sell = None
    _best_buy_historic = None
    _best_sell_historic = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    class Meta:
        ordering = ["-id"]

    @property
    def fullname(self):
        return f"{self.category} - {self.name}"

    @property
    def average_buy(self):
        return self.average_price

    @property
    def max_profit(self):
        buy, sell = self.best_listings
        if not buy or not sell:
            return 0
        return buy.demand_price - sell.supply_price

    @property
    def max_profit_historic(self):
        buy, sell = self.best_listings_historic
        if not buy or not sell:
            return 0
        return buy.demand_price - sell.supply_price

    @property
    def best_buy(self):
        return self.best_listings[0]

    @property
    def best_sell(self):
        return self.best_listings[1]

    @property
    def best_buy_historic(self):
        return self.best_listings_historic[0]

    @property
    def best_sell_historic(self):
        return self.best_listings_historic[1]

    @property
    def best_listings(self) -> ("LiveListing", "LiveListing"):
        if not self._best_buy or self._best_sell:
            try:
                self._best_buy, self._best_sell = cache.get(f"best_{self.id}")
            except TypeError:
                self._best_buy, self._best_sell = (None, None)
        return self._best_buy, self._best_sell

    @property
    def best_listings_historic(self):
        if not self._best_buy_historic or self._best_sell_historic:
            try:
                self._best_buy_historic, self._best_sell_historic = cache.get(
                    f"best_historic_{self.id}"
                )
            except TypeError:
                (
                    self._best_buy_historic,
                    self._best_sell_historic,
                ) = self.find_best_listings_historic(datetime.timedelta(days=14))
        return self._best_buy_historic, self._best_sell_historic

    def find_best_listings_historic(
        self, timespan: datetime.timedelta = datetime.timedelta(days=14)
    ):
        print(f"Calculating historic_listings for {self.id}")
        # TODO: Cache these results?
        historic_listings = list(
            HistoricListing.objects.filter(
                Q(commodity_id=self.id) & Q(datetime__gte=timezone.now() - timespan)
            )
        )
        if not historic_listings:
            print(f"No historic_listings for {self.id}")
            self._best_sell_historic = None
            self._best_buy_historic = None
            cache.set(f"best_historic_{self.id}", (None, None), timeout=3600 / 2)
            return None, None
        if self.best_buy:
            historic_listings.append(self.best_buy)
        if self.best_sell:
            historic_listings.append(self.best_sell)
        best_sell_filtered = list(
            filter(
                lambda hs: hs.is_high_supply() and hs.supply_price > 0,
                historic_listings,
            )
        )
        best_but_filtered = list(
            filter(
                lambda hs: hs.is_high_demand() and hs.demand_price > 0,
                historic_listings,
            )
        )
        if best_sell_filtered:
            self._best_sell_historic = min(
                best_sell_filtered, key=lambda hs: hs.supply_price
            )
        if best_but_filtered:
            self._best_buy_historic = max(
                best_but_filtered, key=lambda hs: hs.demand_price
            )
        cache.set(
            f"best_historic_{self.id}",
            (self._best_buy_historic, self._best_sell_historic),
            timeout=3600 * settings.HISTORIC_CACHE_TIMEOUT_HOURS,
        )
        return self._best_buy_historic, self._best_sell_historic

    def __str__(self):
        return f"{self.fullname}"


class Rare(models.Model):
    name = models.CharField(max_length=100)
    category = models.ForeignKey(
        CommodityCategory, on_delete=models.CASCADE, related_name="rares"
    )
    cost = models.IntegerField()
    max_alloc = models.IntegerField()
    illegal = models.BooleanField()
    suppressed = models.BooleanField()

    tradedangerous_id = models.IntegerField(unique=True, db_index=True)

    @property
    def fullname(self):
        return f"{self.category} - {self.name}"


class System(models.Model):
    name = models.CharField(max_length=100, db_index=True)
    pos_x = models.FloatField()
    pos_y = models.FloatField()
    pos_z = models.FloatField()
    population = models.BigIntegerField(null=True)
    government = models.PositiveSmallIntegerField(
        choices=Governments.choices, null=True
    )
    allegiance = models.PositiveSmallIntegerField(
        choices=Superpowers.choices, null=True
    )

    controlling_faction = models.ForeignKey(
        "Faction", on_delete=models.SET_NULL, related_name="controls", null=True
    )
    # security = models.PositiveSmallIntegerField(choices=SecurityStates.choices, null=True)
    security = models.PositiveSmallIntegerField(
        choices=SystemSecurities.choices, null=True
    )

    tradedangerous_id = models.IntegerField(unique=True, db_index=True)

    class Meta:
        ordering = ["-id"]

    def distance_to(self, other: "System"):
        dX = self.pos_x - other.pos_x
        dY = self.pos_y - other.pos_y
        dZ = self.pos_z - other.pos_z
        return ((dX**2) + (dY**2) + (dZ**2)) ** 0.5

    def distance_to_sol(self):
        # TODO: Save this in DB or a cache so it doesn't need to be recalculated every time.
        dX = self.pos_x
        dY = self.pos_y
        dZ = self.pos_z
        return ((dX**2) + (dY**2) + (dZ**2)) ** 0.5

    @property
    def get_station_names(self):
        return list(
            s.name for s in Station.objects.filter(system_id=self.id).only("name").all()
        )

    def __str__(self):
        return self.name + f"({self.id})"


class Station(models.Model):
    name = models.CharField(max_length=100)
    ls_from_star = models.IntegerField()
    pad_size = models.CharField(max_length=1)
    modified = models.DateTimeField(null=True)
    market = models.BooleanField()
    black_market = models.BooleanField()
    shipyard = models.BooleanField()
    outfitting = models.BooleanField()
    rearm = models.BooleanField()
    refuel = models.BooleanField()
    repair = models.BooleanField()
    planetary = models.BooleanField()
    fleet = models.BooleanField()  # TODO: Maybe index?
    odyssey = models.BooleanField()
    system = models.ForeignKey(
        System, on_delete=models.CASCADE, related_name="stations"
    )
    tradedangerous_id = models.IntegerField(unique=True, db_index=True, null=True)

    class Meta:
        ordering = ["-id"]

    @property
    def station_type(self):
        if self.fleet:
            return StationType.FLEET
        elif self.planetary:
            return StationType.PLANETARY
        else:
            return StationType.STATION

    @property
    def fullname(self):
        station_type_str = (
            self.station_type.value
            if not self.station_type == StationType.STATION
            else ""
        )
        return f"{self.name}" + (f" ({station_type_str})" if station_type_str else "")

    @property
    def is_large_pad(self) -> bool:
        return self.pad_size[0] == "L"

    @property
    def exporting_listings(self):
        return self.listings.filter(Q(supply_units__gt=0))

    @property
    def importing_listings(self):
        return self.listings.filter(Q(demand_units__gt=0))

    @property
    def age_string(self):
        return datetime_to_age_string(self.modified)

    def set_listings(self, listings_list: ["LiveListing"]):
        # with transaction.atomic():
        exising_listings = {
            ll.commodity_id: ll
            for ll in LiveListing.objects.filter(station_id=self.id).all()
        }
        # To delete is everything minus updated.
        updated_listings: {int: LiveListing} = {}
        new_listings = []
        new_historic_listings = []

        new_ll: LiveListing
        for new_ll in listings_list:
            existing_match: LiveListing = exising_listings.get(new_ll.commodity_id)
            if existing_match:
                # Update an existing listing
                if not self.fleet:
                    if (
                        difference_percent(
                            existing_match.demand_price, new_ll.demand_price
                        )
                        > settings.HISTORIC_DIFFERENCE_DELTA
                        or difference_percent(
                            existing_match.supply_price, new_ll.supply_price
                        )
                        > settings.HISTORIC_DIFFERENCE_DELTA
                    ):
                        new_historic_listings.append(
                            HistoricListing.from_live(existing_match)
                        )

                existing_match.demand_price = new_ll.demand_price
                existing_match.demand_units = new_ll.demand_units
                existing_match.supply_price = new_ll.supply_price
                existing_match.supply_units = new_ll.supply_units
                existing_match.modified = new_ll.modified
                existing_match.from_live = new_ll.from_live
                updated_listings[existing_match.id] = existing_match
            else:
                # It's a new listing.
                new_listings.append(new_ll)

        if updated_listings:
            with transaction.atomic():
                to_update = LiveListing.objects.select_for_update().filter(
                    pk__in=sorted(updated_listings.keys())
                )
                for to_update_ll in to_update:
                    for attribute in [
                        "demand_price",
                        "demand_units",
                        "supply_price",
                        "supply_units",
                        "modified",
                        "from_live",
                    ]:
                        to_update_ll.__setattr__(
                            attribute,
                            updated_listings[to_update_ll.id].__getattribute__(
                                attribute
                            ),
                        )
                    to_update_ll.save()
        if updated_listings:
            LiveListing.objects.filter(
                Q(station_id=self.id)
                & ~Q(pk__in=[ll_id for ll_id, ll in updated_listings.items()])
            ).delete()

        if new_listings:
            LiveListing.objects.bulk_create(new_listings)

        if new_historic_listings:
            HistoricListing.objects.bulk_create(new_historic_listings)

    @property
    def services_lists(self):
        enabled = []
        disabled = []
        for is_true, service_string in [
            (self.market, "Market"),
            (self.black_market, "Black Market"),
            (self.shipyard, "Shipyard"),
            (self.outfitting, "Outfitting"),
            (self.rearm, "Rearm"),
            (self.refuel, "Refuel"),
            (self.repair, "Repair"),
        ]:
            if is_true:
                enabled.append(service_string)
            else:
                disabled.append(service_string)
        return enabled, disabled

    @property
    def enabled_services(self):
        return self.services_lists[0]

    @property
    def disabled_services(self):
        return self.services_lists[1]

    @property
    def is_live(self):
        return (
            self.data_age_days != -1 and self.data_age_days * 24 * 60 < IS_LIVE_MINUTES
        )

    def __str__(self):
        return f"{self.fullname} in system with id={self.system_id}"


class LiveListing(models.Model):
    # objects = BulkUpdateOrCreateQuerySet.as_manager()

    commodity: Commodity = models.ForeignKey(
        Commodity, on_delete=models.CASCADE, related_name="listings"
    )
    commodity_tradedangerous_id = models.IntegerField()
    station: Station = models.ForeignKey(
        Station, on_delete=models.CASCADE, related_name="listings"
    )
    station_tradedangerous_id = models.IntegerField(db_index=True, null=True)
    demand_price = models.IntegerField()
    demand_units = models.IntegerField()
    supply_price = models.IntegerField()
    supply_units = models.IntegerField()
    modified = models.DateTimeField()
    from_live = models.BooleanField()

    class Meta:
        ordering = ["-id"]

    @property
    def is_recently_modified(self):
        return (
            datetime.datetime.now(tz=datetime.timezone.utc) - self.modified
        ).days < 30

    def is_high_supply(self, minimum=5000):
        return self.supply_units > minimum

    def is_high_demand(self, minimum=200):
        return self.demand_units > minimum

    def cache_if_better(self) -> (bool, bool):
        """
        TODO: This is a mess.
        :return: Boolean indicating if it was cached
        """
        modified_buy = False
        modified_sell = False
        try:
            original_best_buy, original_best_sell = cache.get(
                f"best_{self.commodity_id}"
            )
        except TypeError:
            original_best_buy, original_best_sell = (None, None)

        best_buy = original_best_buy
        best_sell = original_best_sell
        if self.is_recently_modified:
            if original_best_buy and self.station_id == original_best_buy.station_id:
                best_buy = self
                modified_buy = True
            elif self.is_high_demand() and self.demand_price > 0:
                if not best_buy or is_listing_better_than(self, best_buy, "demand"):
                    best_buy = self
                    modified_buy = True

            if original_best_sell and self.station_id == original_best_sell.station_id:
                best_sell = self
                modified_sell = True
            elif self.is_high_supply() and self.supply_price > 0:
                if not best_sell or is_listing_better_than(self, best_sell, "supply"):
                    best_sell = self
                    modified_sell = True

        if modified_buy or modified_sell:
            is_fleet = self.station.station_type == StationType.FLEET
            if modified_buy and is_fleet:
                modified_buy = False
                best_buy = original_best_buy
            if modified_sell and is_fleet:
                modified_sell = False
                best_buy = original_best_sell
        if modified_buy or modified_sell:
            cache.set(f"best_{self.commodity_id}", (best_buy, best_sell), timeout=None)
            # if (best_buy and original_best_buy.station_id != best_buy.station_id) or \
            #         (best_sell and original_best_sell.station_id != best_sell.station_id) or \
            #         (best_buy and original_best_buy.demand_price != best_buy.demand_price) or \
            #         (best_sell and original_best_sell.supply_price != best_sell.supply_price):
            #     # Only recalculate historic cache if something actually changed.
            #     self.commodity.find_best_listings_historic()

            self.commodity._best_buy = best_buy
            self.commodity._best_sell = best_buy

        return modified_buy, modified_sell

    @property
    def age_string(self):
        return datetime_to_age_string(self.modified)

    def __str__(self):
        return f"{self.commodity.name} @ {self.station.fullname} ({self.station.id}) S:{self.supply_units}@{self.supply_price} and B:{self.demand_units}@{self.demand_price}"


class HistoricListing(models.Model):
    commodity = models.ForeignKey(
        Commodity, on_delete=models.CASCADE, related_name="historic_listings"
    )
    station = models.ForeignKey(
        Station, on_delete=models.CASCADE, related_name="historic_listings"
    )
    demand_price = models.IntegerField()
    demand_units = models.IntegerField()
    supply_price = models.IntegerField()
    supply_units = models.IntegerField()
    datetime = models.DateTimeField()

    class Meta:
        index_together = [
            ("commodity_id", "station_id"),
        ]

    def is_high_supply(self, minimum=5000):
        return self.supply_units > minimum

    def is_high_demand(self, minimum=200):
        return self.demand_units > minimum

    @classmethod
    def from_live(cls, live_listing: LiveListing):
        return cls(
            commodity=live_listing.commodity,
            station=live_listing.station,
            demand_price=live_listing.demand_price,
            demand_units=live_listing.demand_units,
            supply_price=live_listing.supply_price,
            supply_units=live_listing.supply_units,
            datetime=live_listing.modified,
        )

    @property
    def age_string(self):
        return datetime_to_age_string(self.datetime)

    def __str__(self):
        return f"{self.commodity.name} on {self.datetime} @ {self.station.fullname} ({self.station.id}) S:{self.supply_units}@{self.supply_price} and B:{self.demand_units}@{self.demand_price}"


class CarrierMission(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    mode = models.CharField(max_length=1)
    station: Station = models.ForeignKey(
        Station, on_delete=models.SET_NULL, null=True, related_name=None
    )
    carrier: Station = models.ForeignKey(
        Station, on_delete=models.SET_NULL, null=True, related_name="missions"
    )
    carrier_name = models.CharField(max_length=128)
    commodity = models.ForeignKey(Commodity, on_delete=models.SET_NULL, null=True)
    units = models.IntegerField()
    worker_profit = models.IntegerField()
    active = models.BooleanField()
    date_posted = models.DateTimeField()
    date_completed = models.DateTimeField(null=True)

    _station_live_listing = None
    _carrier_live_listing = None

    @property
    def station_live_listing(self) -> LiveListing:
        if not self._station_live_listing:
            self._station_live_listing = LiveListing.objects.filter(
                Q(station_id=self.station.id) & Q(commodity_id=self.commodity.id)
            ).first()
        return self._station_live_listing

    @property
    def carrier_live_listing(self) -> LiveListing:
        if not self._carrier_live_listing:
            self._carrier_live_listing = LiveListing.objects.filter(
                Q(station_id=self.carrier.id) & Q(commodity_id=self.commodity.id)
            ).first()
        return self._carrier_live_listing

    @property
    def station_units(self):
        if self.carrier_live_listing:
            if self.is_loading:
                return self.station_live_listing.supply_units
            else:
                return self.station_live_listing.demand_units
        else:
            return "Unknown"

    @property
    def carrier_units(self):
        if self.carrier_live_listing:
            if self.is_loading:
                return self.carrier_live_listing.demand_units
            else:
                return self.carrier_live_listing.supply_units
        else:
            return "Unknown"

    @property
    def current_profit(self):
        if self.station_live_listing and self.carrier_live_listing:
            if self.is_loading:
                return (
                    self.carrier_live_listing.demand_price
                    - self.station_live_listing.supply_price
                )
            else:
                return (
                    self.station_live_listing.demand_price
                    - self.carrier_live_listing.supply_price
                )
        return self.worker_profit

    @property
    def is_loading(self):
        return self.mode == "L"

    @property
    def is_unloading(self):
        return self.mode == "U"

    @property
    def progress(self):
        if self.carrier_live_listing:
            if self.is_unloading:
                return 100 - int(
                    self.carrier_live_listing.demand_units / self.units * 100
                )
            else:
                return int(self.carrier_live_listing.demand_units / self.units * 100)
        else:
            return 0

    @property
    def is_live(self):
        return self.carrier.is_live  # or self.station.is_live


class State(models.Model):
    name = models.CharField(max_length=100, choices=States.choices)

    def __str__(self):
        return f"{self.name}"


# class EconomyState(models.Model):
#     name = models.CharField(max_length=100, choices=EconomyStates.choices)
#
#     def __str__(self):
#         return f"{self.name}"


class LocalFaction(models.Model):
    faction = models.ForeignKey(
        "Faction", on_delete=models.CASCADE, related_name="states"
    )
    system = models.ForeignKey(
        System, on_delete=models.CASCADE, related_name="local_factions"
    )
    states = models.ManyToManyField(State, related_name="factions")
    recovering_states = models.ManyToManyField(
        State, related_name="recovering_factions"
    )
    pending_states = models.ManyToManyField(State, related_name="pending_factions")
    happiness = models.PositiveSmallIntegerField(
        choices=FactionHappiness.choices, null=True
    )
    influence = models.FloatField()
    modified = models.DateTimeField(null=True)



    def has_states_changed(
        self, states: [], recovering_states: [], pending_states: []
    ) -> bool:
        states_ids = [f.id for f in self.states.only("id").order_by("id").all()]
        if states_ids != list(sorted([s.value for s in states])):
            return True

        recovering_states_ids = [
            f.id for f in self.recovering_states.only("id").order_by("id").all()
        ]
        if recovering_states_ids != list(sorted([s.value for s in recovering_states])):
            return True

        pending_states_ids = [
            f.id for f in self.pending_states.only("id").order_by("id").all()
        ]

        if pending_states_ids != list(sorted([s.value for s in pending_states])):
            return True

        return False

    def __str__(self):
        return f"{self.faction} in {self.system}"


class Faction(models.Model):
    name = models.CharField(max_length=100)
    home_system = models.ForeignKey(
        System, on_delete=models.SET_NULL, related_name="factions", null=True
    )
    allegiance = models.PositiveSmallIntegerField(
        choices=Superpowers.choices, null=True
    )
    government = models.PositiveSmallIntegerField(
        choices=Governments.choices, null=True
    )
    is_player = models.BooleanField()
    tradedangerous_id = models.IntegerField(unique=True, null=True)

    def __str__(self):
        return f"{self.name}" + "" if not self.is_player else f" (Player) "
