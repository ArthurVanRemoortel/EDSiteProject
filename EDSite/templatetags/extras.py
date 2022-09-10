import json
from pprint import pprint

from django import template
from django.core import serializers
from django.http import JsonResponse
from django.utils.safestring import mark_safe

from EDSite.models import Station
from EDSite.serializers import StationSerializer

register = template.Library()


@register.filter
def index(indexable, i):
    return indexable[i]


@register.filter
def get_value(h, key):
    return h.get(key, None)


@register.filter
def js(obj):
    if isinstance(obj, Station):
        ser = StationSerializer(obj).data
        return ser
