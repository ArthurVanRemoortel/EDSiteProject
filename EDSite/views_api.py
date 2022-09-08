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
        name_like = self.request.query_params.get('name_like')
        if name_like:
            qs = qs.filter(Q(name__icontains=name_like))
        return qs.all()


class ListingsViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.ListingsSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        return LiveListing.objects.all()#.prefetch_related('commodity', 'station')


class SystemsViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.SystemSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        qs = System.objects
        name_like = self.request.query_params.get('name_like')
        if name_like:
            qs = qs.filter(Q(name__icontains=name_like))
        return qs.all()


class StationsViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.StationSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        qs = Station.objects
        name_like = self.request.query_params.get('name_like')
        if name_like:
            qs = qs.filter(Q(name__icontains=name_like))
        return qs.all()
