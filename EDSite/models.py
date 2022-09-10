import random

from django.db import models
from django.db.models import Q
from EDSite.helpers import StationType, difference_percent
from django.core.cache import cache
import datetime
from django.conf import settings
from bulk_update_or_create import BulkUpdateOrCreateQuerySet
from django.db import transaction
from pprint import pprint
from django.forms.models import model_to_dict

IS_LIVE_MINUTES = 60


class CommodityCategory(models.Model):
    name = models.CharField(max_length=100)
    tradedangerous_id = models.IntegerField(unique=True, db_index=True)

    @property
    def sorted_commodities(self):
        return self.commodities.all().order_by('name')

    def __str__(self):
        return self.name


class Commodity(models.Model):
    name = models.CharField(max_length=100)
    category = models.ForeignKey(CommodityCategory, on_delete=models.CASCADE, related_name='commodities')
    average_price = models.IntegerField()

    game_id = models.IntegerField(unique=True, db_index=True)
    tradedangerous_id = models.IntegerField(unique=True, db_index=True)

    best_buy = None
    best_sell = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update_best_listings()

    class Meta:
        ordering = ['-id']

    @property
    def fullname(self):
        return f'{self.category} - {self.name}'

    def average_buy(self):
        return self.average_price

    @property
    def max_profit(self):
        buy, sell = self.best_listings
        if not buy or not sell:
            return 0
        return buy.demand_price - sell.supply_price

    def update_best_listings(self) -> ('LiveListing', 'LiveListing'):
        try:
            self.best_buy, self.best_sell = cache.get(f'best_{self.id}')
        except TypeError:
            self.best_buy, self.best_sell = (None, None)

    @property
    def best_listings(self) -> ('LiveListing', 'LiveListing'):
        return self.best_buy, self.best_sell

    def __str__(self):
        return f'{self.fullname}'


class Rare(models.Model):
    name = models.CharField(max_length=100)
    category = models.ForeignKey(CommodityCategory, on_delete=models.CASCADE, related_name='rares')
    cost = models.IntegerField()
    max_alloc = models.IntegerField()
    illegal = models.BooleanField()
    suppressed = models.BooleanField()

    tradedangerous_id = models.IntegerField(unique=True, db_index=True)

    @property
    def fullname(self):
        return f'{self.category} - {self.name}'


class System(models.Model):
    name = models.CharField(max_length=100, db_index=True)
    pos_x = models.FloatField()
    pos_y = models.FloatField()
    pos_z = models.FloatField()

    tradedangerous_id = models.IntegerField(unique=True, db_index=True)

    class Meta:
        index_together = [
            ("pos_x", "pos_y", "pos_z"),
        ]
        ordering = ['-id']

    def distance_to(self, other: 'System'):
        dX = (self.pos_x - other.pos_x)
        dY = (self.pos_y - other.pos_y)
        dZ = (self.pos_z - other.pos_z)
        return ((dX ** 2) + (dY ** 2) + (dZ ** 2)) ** 0.5

    def distance_to_sol(self):
        # TODO: Save this in DB or a cache so it doesn't need to be recalculated every time.
        dX = self.pos_x
        dY = self.pos_y
        dZ = self.pos_z
        return ((dX ** 2) + (dY ** 2) + (dZ ** 2)) ** 0.5

    def __str__(self):
        return self.name + f"({self.id})"


class Station(models.Model):
    name = models.CharField(max_length=100)
    ls_from_star = models.IntegerField()
    pad_size = models.CharField(max_length=1)
    item_count = models.IntegerField()
    # data_age_days = models.FloatField()
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

    system = models.ForeignKey(System, on_delete=models.CASCADE, related_name='stations')
    tradedangerous_id = models.IntegerField(unique=True, db_index=True)

    class Meta:
        ordering = ['-id']

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
        station_type_str = self.station_type.value if not self.station_type == StationType.STATION else ''
        return f'{self.name}' + (f' ({station_type_str})' if station_type_str else '')

    @property
    def is_large_pad(self) -> bool:
        return self.pad_size[0] == 'L'

    @property
    def exporting_listings(self):
        return self.listings.filter(Q(supply_units__gt=0))

    @property
    def importing_listings(self):
        return self.listings.filter(Q(demand_units__gt=0))

    @property
    def modified_string(self):
        if not self.modified:
            return "Unknown"
        age_delta: datetime.timedelta = datetime.datetime.now(tz=datetime.timezone.utc) - self.modified
        if age_delta.seconds < 3600:
            return f"{int(age_delta.seconds / 60)} minutes"
        elif age_delta.days < 1:
            return f"{int(age_delta.seconds / 3600)} hours"
        else:
            return f"{age_delta.days} days"

    def set_listings(self, listings_list: ['LiveListing']):
        # with transaction.atomic():
        exising_listings = {ll.commodity_id: ll for ll in LiveListing.objects.filter(station_tradedangerous_id=self.tradedangerous_id).all()}
        # To delete is everything minus updated.
        updated_listings = []
        new_listings = []
        new_historic_listings = []

        new_ll: LiveListing
        for new_ll in listings_list:
            existing_match: LiveListing = exising_listings.get(new_ll.commodity_id)
            if existing_match:
                # Update an existing listing
                if not self.fleet:
                    if (difference_percent(existing_match.demand_price, new_ll.demand_price) > 10
                            or difference_percent(existing_match.supply_price, new_ll.supply_price) > 10):
                        new_historic_listings.append(HistoricListing.from_live(existing_match))

                existing_match.demand_price = new_ll.demand_price
                existing_match.demand_units = new_ll.demand_units
                existing_match.supply_price = new_ll.supply_price
                existing_match.supply_units = new_ll.supply_units
                existing_match.modified     = new_ll.modified
                existing_match.from_live    = new_ll.from_live
                updated_listings.append(existing_match)
            else:
                # It's a new listing.
                new_listings.append(new_ll)

        if updated_listings:
            # print("Updating:", len(updated_listings))
            with transaction.atomic():
                for updated_ll in updated_listings:
                    e = LiveListing.objects.select_for_update().filter(id=updated_ll.id)
                    e.update(
                        **{key: value for key, value in model_to_dict(updated_ll).items() if
                           key in ['demand_price', 'demand_units', 'supply_price', 'supply_units', 'modified',
                                   'from_live']})

        if updated_listings:
            LiveListing.objects.filter(Q(station_tradedangerous_id=self.tradedangerous_id) & ~Q(pk__in=[ll.id for ll in updated_listings])).delete()

        if new_listings:
            LiveListing.objects.bulk_create(new_listings)

        if new_historic_listings:
            HistoricListing.objects.bulk_create(new_historic_listings)

    @property
    def is_live(self):
        return self.data_age_days != -1 and self.data_age_days * 24 * 60 < IS_LIVE_MINUTES

    def __str__(self):
        return f'{self.fullname}'


class LiveListing(models.Model):
    # objects = BulkUpdateOrCreateQuerySet.as_manager()

    commodity: Commodity = models.ForeignKey(Commodity, on_delete=models.CASCADE, related_name='listings')
    commodity_tradedangerous_id = models.IntegerField()
    station: Station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name='listings')
    station_tradedangerous_id = models.IntegerField(db_index=True)
    demand_price = models.IntegerField()
    demand_units = models.IntegerField()
    supply_price = models.IntegerField()
    supply_units = models.IntegerField()
    modified = models.DateTimeField()
    from_live = models.BooleanField()

    class Meta:
        # index_together = [
        #     ("commodity_id", "station_id"),
        # ]
        ordering = ['-id']

    @property
    def is_recently_modified(self):
        return (datetime.datetime.now(tz=datetime.timezone.utc) - self.modified).days < 30

    def is_high_supply(self, minimum=5000):
        return self.supply_units > minimum

    def is_high_demand(self, minimum=200):
        # if self.station.station_type == StationType.FLEET:
        #     return self.demand_units > 200
        return self.demand_units > minimum

    @property
    def modified_string(self):
        age_delta: datetime.timedelta = datetime.datetime.now(tz=datetime.timezone.utc) - self.modified
        if age_delta.seconds < 3600:
            return f"{int(age_delta.seconds / 60)} minutes"
        elif age_delta.days < 1:
            return f"{int(age_delta.seconds / 3600)} hours"
        else:
            return f"{age_delta.days} days"

    def __str__(self):
        return f'{self.commodity.name} @ {self.station.fullname} ({self.station.id}) S:{self.supply_units}@{self.supply_price} and B:{self.demand_units}@{self.demand_price}'


class HistoricListing(models.Model):
    commodity = models.ForeignKey(Commodity, on_delete=models.CASCADE, related_name='historic_listings')
    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name='historic_listings')
    demand_price = models.IntegerField()
    demand_units = models.IntegerField()
    supply_price = models.IntegerField()
    supply_units = models.IntegerField()
    datetime = models.DateTimeField()

    class Meta:
        index_together = [
            ("commodity_id", "station_id"),
        ]

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


class CarrierMission(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    mode = models.CharField(max_length=1)
    station: Station = models.ForeignKey(Station, on_delete=models.SET_NULL, null=True, related_name=None)
    carrier: Station = models.ForeignKey(Station, on_delete=models.SET_NULL, null=True, related_name='missions')
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
            if self.station.tradedangerous_id:
                self._station_live_listing = LiveListing.objects.filter(Q(station_tradedangerous_id=self.station.tradedangerous_id) & Q(commodity_id=self.commodity.id)).first()
            else:
                self._station_live_listing = self.station.listings.filter(Q(commodity_id=self.commodity.id)).first()
        return self._station_live_listing

    @property
    def carrier_live_listing(self) -> LiveListing:
        if not self._carrier_live_listing:
            if self.carrier.tradedangerous_id:
                self._carrier_live_listing = LiveListing.objects.filter(Q(station_tradedangerous_id=self.carrier.tradedangerous_id) & Q(commodity_id=self.commodity.id)).first()
            else:
                self._carrier_live_listing = self.carrier.listings.filter(Q(commodity_id=self.commodity.id)).first()
        return self._carrier_live_listing

    @property
    def station_units(self):
        if self.carrier_live_listing:
            if self.is_loading:
                return self.station_live_listing.supply_units
            else:
                return self.station_live_listing.demand_units
        else:
            return 'Unknown'

    @property
    def carrier_units(self):
        if self.carrier_live_listing:
            if self.is_loading:
                return self.carrier_live_listing.demand_units
            else:
                return self.carrier_live_listing.supply_units
        else:
            return 'Unknown'

    @property
    def current_profit(self):
        if self.station_live_listing and self.carrier_live_listing:
            if self.is_loading:
                return self.carrier_live_listing.demand_price - self.station_live_listing.supply_price
            else:
                return self.station_live_listing.demand_price - self.carrier_live_listing.supply_price
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
                return 100 - int(self.carrier_live_listing.demand_units/self.units*100)
            else:
                return int(self.carrier_live_listing.demand_units/self.units*100)
        else:
            return 0

    @property
    def is_live(self):
        return self.carrier.is_live# or self.station.is_live
