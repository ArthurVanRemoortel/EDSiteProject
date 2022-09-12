import json
from pprint import pprint

from django import template
from django.core import serializers
from django.http import JsonResponse
from django.utils.safestring import mark_safe

from EDSite.models import Station, System, Commodity
from EDSite.serializers import StationSerializer

register = template.Library()


@register.filter
def index(indexable, i):
    return indexable[i]


@register.filter
def external_url(obj, site):
    if isinstance(obj, System):
        if site == "inara":
            return f"https://inara.cz/elite/starsystem/?search={obj.name}"
        elif site == "eddb":
            return f"https://eddb.io/system/{obj.tradedangerous_id}"
    elif isinstance(obj, Station):
        if site == "inara":
            return f"https://inara.cz/elite/station/?search={obj.name} [{obj.system.name}]"
        elif site == "eddb":
            return f"https://eddb.io/station/{obj.tradedangerous_id}"
    elif isinstance(obj, Commodity):
        if site == "inara":
            return None
        elif site == "eddb":
            return f"https://eddb.io/commodity/{obj.tradedangerous_id}"


@register.filter
def get_value(h, key):
    return h.get(key, None)


@register.filter
def js(obj):
    if isinstance(obj, Station):
        ser = StationSerializer(obj).data
        return ser


@register.inclusion_tag('EDSite/snippets/sized_icon.html')
def sized_icon(img_name, size):
    return {'img_name': img_name, 'size': size, 'rounded': False}


@register.inclusion_tag('EDSite/snippets/sized_icon.html')
def sized_rounded_icon(img_name, size):
    base_template = sized_icon(img_name, size)
    base_template['rounded'] = True
    return base_template


@register.inclusion_tag('EDSite/snippets/open_external.html')
def open_external(trigger_id, obj, placement):
    return {'trigger_id': trigger_id, 'object': obj, 'placement': placement}
