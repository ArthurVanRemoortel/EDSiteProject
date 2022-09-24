from django.contrib.auth.models import User, Group
from rest_framework import serializers

from EDSite.models import Commodity, LiveListing, Station, System


class CommoditySerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Commodity
        fields = ["id", "name", "average_price", "game_id", "tradedangerous_id"]


class SystemSerializer(serializers.HyperlinkedModelSerializer):
    government_id = "test"
    government_name = serializers.CharField(source="get_government_display")
    allegiance_name = serializers.CharField(source="get_allegiance_display")
    security_name = serializers.CharField(source="get_security_display")
    # station_names = serializers.SerializerMethodField('get_station_names')

    class Meta:
        model = System
        depth = 1
        fields = [
            "id",
            "name",
            "pos_x",
            "pos_y",
            "pos_z",
            "tradedangerous_id",
            "population",
            "government",
            "government_name",
            "allegiance",
            "allegiance_name",
            "security",
            "security_name",
            # "station_names",
        ]

    def get_station_names(self, obj):
        return obj.get_station_names


class StationSerializer(serializers.HyperlinkedModelSerializer):
    system = SystemSerializer()

    class Meta:
        model = Station
        fields = [
            "id",
            "name",
            "ls_from_star",
            "pad_size",
            "modified",
            "market",
            "black_market",
            "shipyard",
            "outfitting",
            "rearm",
            "refuel",
            "repair",
            "planetary",
            "fleet",
            "odyssey",
            "system",
            "tradedangerous_id",
        ]


class ListingsSerializer(serializers.HyperlinkedModelSerializer):
    commodity = CommoditySerializer()
    station = StationSerializer()

    class Meta:
        model = LiveListing
        fields = [
            "id",
            "station",
            "commodity",
            "demand_price",
            "demand_units",
            "supply_price",
            "supply_units",
            "modified",
            "from_live",
        ]

        read_only_fields = []
        search_fields = ["id"]
