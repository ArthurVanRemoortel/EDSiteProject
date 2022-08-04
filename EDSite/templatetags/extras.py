
from django import template
register = template.Library()


@register.filter
def index(indexable, i):
    return indexable[i]

@register.filter
def get_value(h, key):
    return h.get(key, None)
