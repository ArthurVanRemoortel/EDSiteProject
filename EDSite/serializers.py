from django.contrib.auth.models import User, Group
from rest_framework import serializers

from EDSite.models import Commodity, LiveListing, Station, System


class CommoditySerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Commodity
        fields = ['id', 'name', 'average_price', 'game_id', 'tradedangerous_id']


class SystemSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = System
        fields = ['id', 'name', 'pos_x', 'pos_y', 'pos_z', 'tradedangerous_id']


class StationSerializer(serializers.HyperlinkedModelSerializer):
    system = SystemSerializer()

    class Meta:
        model = Station
        fields = ['id', 'name', 'ls_from_star', 'pad_size', 'item_count', 'modified', 'market',
                  'black_market', 'shipyard', 'outfitting', 'rearm', 'refuel', 'repair', 'planetary',
                  'fleet', 'odyssey', 'system', 'tradedangerous_id'
                  ]


class ListingsSerializer(serializers.HyperlinkedModelSerializer):
    # commodity = serializers.SlugRelatedField(read_only=True, slug_field='name')
    # commodity = serializers.HyperlinkedRelatedField(read_only=True, view_name='CommoditiesViewSet')
    commodity = CommoditySerializer()
    station = StationSerializer()
    # commodity = serializers.PrimaryKeyRelatedField(read_only=True)
    # station = serializers.RelatedField(read_only=True)

    class Meta:
        model = LiveListing
        fields = ['id', 'station', 'commodity',
                  'demand_price', 'demand_units', 'supply_price', 'supply_units', 'modified', 'from_live']

        read_only_fields = []
        search_fields = ['id']