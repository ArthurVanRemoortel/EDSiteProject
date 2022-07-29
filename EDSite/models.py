from django.db import models

from EDSite.helpers import StationType
from django.core.cache import cache
import datetime
from django.conf import settings


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


class Station(models.Model):
    name = models.CharField(max_length=100)
    ls_from_star = models.IntegerField()
    pad_size = models.CharField(max_length=1)
    item_count = models.IntegerField()
    data_age_days = models.FloatField()

    market = models.BooleanField()
    black_market = models.BooleanField()
    shipyard = models.BooleanField()
    outfitting = models.BooleanField()
    rearm = models.BooleanField()
    refuel = models.BooleanField()
    repair = models.BooleanField()
    planetary = models.BooleanField()
    fleet = models.BooleanField() # TODO: Maybe index?
    odyssey = models.BooleanField()

    system = models.ForeignKey(System, on_delete=models.CASCADE, related_name='stations')
    tradedangerous_id = models.IntegerField(unique=True, db_index=True)

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
        return f'{self.name} ({self.system.name})' + (f' ({station_type_str})' if station_type_str else '')

    @property
    def is_large_pad(self) -> bool:
        return self.pad_size[0] == 'L'

    @property
    def exporting_listings(self):
        return self.listings.filter(Q(supply_level__gt=0))

    @property
    def importing_listings(self):
        return self.listings.filter(Q(demand_units__gt=0))

    def __str__(self):
        return f'{self.fullname in self.system.name}'


class LiveListing(models.Model):
    commodity: Commodity = models.ForeignKey(Commodity, on_delete=models.CASCADE, related_name='listings', db_index=True)
    station: Station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name='listings', db_index=True)
    demand_price = models.IntegerField()
    demand_units = models.IntegerField()
    demand_level = models.IntegerField()
    supply_price = models.IntegerField()
    supply_units = models.IntegerField()
    supply_level = models.IntegerField()
    modified = models.DateTimeField()
    from_live = models.BooleanField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['commodity', 'station'], name='Unique combination of commodity and station.')
        ]
        # index_together = [
        #     ("commodity", "station", "modified"),
        # ]

        ordering = ['-id']

    @property
    def is_recently_modified(self):
        return (datetime.datetime.now(tz=datetime.timezone.utc) - self.modified).days < 30

    def is_high_supply(self, minimum=5000):
        return self.supply_units > minimum

    def is_high_demand(self, minimum=5000):
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
    station = models.ForeignKey(Station, on_delete=models.CASCADE)
    demand_price = models.IntegerField()
    demand_units = models.IntegerField()
    demand_level = models.IntegerField()
    supply_price = models.IntegerField()
    supply_units = models.IntegerField()
    supply_level = models.IntegerField()
    datetime = models.DateTimeField()

    class Meta:
        index_together = [
            ("commodity", "station"),
        ]

    @classmethod
    def from_live(cls, live_listing: LiveListing):
        return cls(
            commodity=live_listing.commodity,
            station=live_listing.station,
            demand_price=live_listing.demand_price,
            demand_units=live_listing.demand_units,
            demand_level=live_listing.demand_level,
            supply_price=live_listing.supply_price,
            supply_units=live_listing.supply_units,
            supply_level=live_listing.supply_level,
            datetime=live_listing.modified,
        )


class CarrierTrade(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    mode = models.CharField(max_length=1)
    station = models.ForeignKey(Station, on_delete=models.SET_NULL, null=True)
    commodity = models.ForeignKey(Commodity, on_delete=models.SET_NULL, null=True)
    units = models.IntegerField()
    price = models.IntegerField()
    active = models.BooleanField()
    date_posted = models.DateTimeField()
    date_completed = models.DateTimeField()


    def station_units(self):
        live_listing: LiveListing = self.station.listings.filter(Q(commodity_id=self.commodity.id))

    def current_profit(self):
        ...

    @property
    def is_loading(self):
        return self.mode == "L"

    @property
    def is_unloading(self):
        return self.mode == "U"
