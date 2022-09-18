from pprint import pprint

from django.db.models import Q
from django.http import HttpResponse
from rest_framework import viewsets, permissions, generics

from EDSite.models import Commodity, LiveListing, System, Station
from EDSite import serializers


class CommoditiesViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.CommoditySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        qs = Commodity.objects
        name_like = self.request.query_params.get("name_like")
        if name_like:
            qs = qs.filter(Q(name__icontains=name_like))
        return qs.all()


class ListingsViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.ListingsSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        qs = LiveListing.objects
        commodity_id = self.request.query_params.get("commodity")
        station_id = self.request.query_params.get("station")
        system_id = self.request.query_params.get("system__station")
        type = self.request.query_params.get("type")  # Supply or demand.
        units = self.request.query_params.get("units")
        if station_id:
            qs = qs.filter(Q(station_id=station_id))
        if commodity_id:
            qs = qs.filter(Q(commodity_id=commodity_id))
        if system_id:
            qs = qs.filter(Q(station__system=system_id))
        if type:
            if type == "supply":
                if units:
                    qs = qs.filter(Q(supply_units__gte=units))
                else:
                    qs = qs.filter(Q(supply_units__gt=0))
                qs = qs.order_by("supply_price")
            elif type == "demand":
                if units:
                    qs = qs.filter(Q(demand_units__gte=units))
                else:
                    qs = qs.filter(Q(demand_units__gt=0))
                qs = qs.order_by("-demand_price")
        return qs.all()  # .prefetch_related('commodity', 'station')


class SystemsViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.SystemSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        qs = System.objects
        name_like = self.request.query_params.get("name_like")
        if name_like:
            qs = qs.filter(Q(name__icontains=name_like))
        return qs.all()


class StationsViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.StationSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        qs = Station.objects
        name_like = self.request.query_params.get("name_like")
        if name_like:
            qs = qs.filter(Q(name__icontains=name_like))
        return qs.all()
