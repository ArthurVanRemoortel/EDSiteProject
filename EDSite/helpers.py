import codecs
import csv
import linecache
import os
from threading import Lock, Thread
from enum import Enum
import datetime as datetime
import tracemalloc
from collections import Counter
import gc
from urllib import request

from tqdm import tqdm


class SingletonMeta(type):
    _instances = {}

    _lock: Lock = Lock()

    def __call__(cls, *args, **kwargs):
        with cls._lock:
            if cls not in cls._instances:
                instance = super().__call__(*args, **kwargs)
                cls._instances[cls] = instance
        return cls._instances[cls]


class EDDatabaseState(Enum):
    UNKNOWN = 0
    UPDATING = 1
    READY = 2


class StationType(Enum):
    FLEET = 'FC'
    PLANETARY = 'P'
    STATION = 'S'


def difference_percent(a, b):
    if a == b:
        return 0
    elif a == 0 or b == 0:
        return 100.0
    return (abs(a - b) / b) * 100.0


def make_timezone_aware(dt: datetime.datetime) -> datetime.datetime:
    return dt.replace(tzinfo=datetime.timezone.utc)


def display_top_memory(snapshot, key_type='lineno', limit=3):
    snapshot = snapshot.filter_traces((
        tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
        tracemalloc.Filter(False, "<unknown>"),
    ))
    top_stats = snapshot.statistics(key_type)

    print("Top %s lines" % limit)
    for index, stat in enumerate(top_stats[:limit], 1):
        frame = stat.traceback[0]
        # replace "/path/to/module/file.py" with "module/file.py"
        filename = os.sep.join(frame.filename.split(os.sep)[-2:])
        print("#%s: %s:%s: %.1f KiB"
              % (index, filename, frame.lineno, stat.size / 1024))
        line = linecache.getline(frame.filename, frame.lineno).strip()
        if line:
            print('    %s' % line)

    other = top_stats[limit:]
    if other:
        size = sum(stat.size for stat in other)
        print("%s other: %.1f KiB" % (len(other), size / 1024))
    total = sum(stat.size for stat in top_stats)
    print("Total allocated size: %.1f KiB" % (total / 1024))


def queryset_iterator(qs, chunk_size = 500, gc_collect = True):
    iterator = qs.values_list('pk', flat=True).order_by('pk').distinct().iterator()
    eof = False
    while not eof:
        primary_key_buffer = []
        try:
            while len(primary_key_buffer) < chunk_size:
                primary_key_buffer.append(iterator.next())
        except StopIteration:
            eof = True
        for obj in qs.filter(pk__in=primary_key_buffer).order_by('pk').iterator():
            yield obj
        if gc_collect:
            gc.collect()


def chunked_queryset(queryset, chunk_size=10000):
    """Slice a queryset into chunks. This is useful to avoid memory issues when
    iterating through large querysets.
    Code adapted from https://djangosnippets.org/snippets/10599/
    """
    if not queryset.exists():
        return
    queryset = queryset.order_by("pk")
    pks = queryset.values_list("pk", flat=True)
    start_pk = pks[0]
    while True:
        try:
            end_pk = pks.filter(pk__gte=start_pk)[chunk_size]
        except IndexError:
            break
        yield queryset.filter(pk__gte=start_pk, pk__lt=end_pk)
        start_pk = end_pk
    yield queryset.filter(pk__gte=start_pk)


def list_to_columns(lst, cols):
    result = []
    for i, value in enumerate(lst):
        if i % cols == 0:
            result.append([])
        result[-1].append(value)
    return result


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def chunks_no_overlap(lst, n):
    result = [[]]
    i = 0
    prev = None
    for value in lst:
        if i >= n and value != prev:
            result.append([])
            i = 0
        result[-1].append(value)
        i += 1
        prev = value
    return result


def update_item_dict():
    # We'll use this to get the fdev_id from the 'symbol', AKA commodity['name'].lower()
    db_name = dict()
    edcd_source = 'https://raw.githubusercontent.com/EDCD/FDevIDs/master/commodity.csv'
    edcd_csv = request.urlopen(edcd_source)
    edcd_dict = csv.DictReader(codecs.iterdecode(edcd_csv, 'utf-8'))
    for line in iter(edcd_dict):
        db_name[line['symbol'].lower()] = line['id']

    # Rare items are in a different file.
    edcd_rare_source = 'https://raw.githubusercontent.com/EDCD/FDevIDs/master/rare_commodity.csv'
    edcd_rare_csv = request.urlopen(edcd_rare_source)
    edcd_rare_dict = csv.DictReader(codecs.iterdecode(edcd_rare_csv, 'utf-8'))
    for line in iter(edcd_rare_dict):
        db_name[line['symbol'].lower()] = line['id']

    # We'll use this to get the commodity_id from the fdev_id because it's faster than a database lookup.
    item_ids = dict()

    # Rare items don't have an EDDB commodity_id, so we'll just store them by the fdev_id
    for line in iter(edcd_rare_dict):
        item_ids[line['id']] = line['id']

    return db_name, item_ids