import datetime
import threading
import time
from pprint import pprint

from django.contrib import messages
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db.models import Q, Count, Prefetch
from django.forms import model_to_dict
from django.http import HttpResponse, JsonResponse, HttpResponseRedirect
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt

# import EDSite.ed_data
from EDSite.tools.ed_data import EDData
from EDSite.forms import CommodityForm, SignupForm, LoginForm, CarrierMissionForm, SystemsForm, StationsForm
from EDSite.helpers import make_timezone_aware, list_to_columns
from EDSite.models import CommodityCategory, Commodity, Station, LiveListing, System, CarrierMission
from EDSiteProject import settings
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm

USER_CARRIER = ('Normandy SR-404', Station.objects.get(pk=203831))
CURRENT_SYSTEM = USER_CARRIER[1].system


if settings.LIVE_UPDATER:
    # TODO: Move this.
    print('Starting the live listener.')
    threading.Thread(target=EDData().start_live_listener, daemon=True).start()
else:
    print('Not starting the live listener.')


def logged_in_user(request):
    return request.user if not request.user.is_anonymous else None


def base_context(request) -> {}:
    return {
        'current_user': logged_in_user(request),
        'current_system': CURRENT_SYSTEM,
        'current_carrier': USER_CARRIER,
        'DEBUG_MODE': settings.DEBUG_MODE
    }


def index(request):
    context = {}
    return render(request, 'EDSite/index.html', base_context(request) | context)


def systems(request):
    context = {}
    ref_system = None
    if request.method == 'GET':
        form = SystemsForm()
        form.fields['only_populated'].initial = 'no'
        filtered_systems = System.objects.order_by('id')
    else:
        form = SystemsForm(request.POST)
        ref_system_name_or_id = form.data.get('reference_system')
        only_populated = form.data.get('only_populated') == 'yes'

        if ref_system_name_or_id and ref_system_name_or_id.isdigit():
            ref_system = System.objects.get(pk=int(ref_system_name_or_id))
        elif ref_system_name_or_id:
            ref_system = System.objects.filter(name__icontains=ref_system_name_or_id).first()

        filtered_systems = System.objects.order_by('id')

        if only_populated:
            filtered_systems = filtered_systems.annotate(num_stations=Count('stations')).filter(num_stations__gt=0)

    filtered_systems = filtered_systems[:40]
    if ref_system:
        print('Reference: ', ref_system)
        distances = {other_system.id: int(other_system.distance_to(ref_system)) for other_system in filtered_systems}
        filtered_systems = sorted(list(filtered_systems), key=lambda filtered_system: distances[filtered_system.id], reverse=False)
        context['reference_distances'] = distances
        context['reference_system'] = ref_system

    context['systems'] = filtered_systems
    context['form'] = form
    return render(request, 'EDSite/system/systems.html', base_context(request) | context)


def system(request, system_id):
    context = {
        'system': System.objects.get(pk=system_id),
    }
    return render(request, 'EDSite/system/system.html', base_context(request) | context)


def stations(request):
    context = {}
    ref_system = None
    system_distance = None
    if request.method == 'GET':
        form = StationsForm()
        filtered_stations = Station.objects.order_by('id')
    else:
        form = StationsForm(request.POST)
        include_fleet_carriers = form.data.get('include_fleet_carriers') == 'yes'
        include_planetary = form.data.get('include_planetary') == 'yes'
        landing_pad_size = form.data.get('landing_pad_size')
        star_distance = form.data.get('star_distance')
        system_distance = form.data.get('system_distance')

        ref_system_name_or_id = form.data.get('reference_system')
        if system_distance and system_distance.isdigit():
            system_distance = int(system_distance)

        if ref_system_name_or_id and ref_system_name_or_id.isdigit():
            ref_system = System.objects.get(pk=int(ref_system_name_or_id))
            filtered_stations = Station.objects.select_related('system').order_by('id')
        elif ref_system_name_or_id:
            ref_system = System.objects.filter(name__icontains=ref_system_name_or_id).order_by('id').first()
            if ref_system:
                filtered_stations = Station.objects.select_related('system').order_by('id')
            else:
                filtered_stations = Station.objects.order_by('id')
        else:
            filtered_stations = Station.objects.order_by('id')

        if star_distance and star_distance.isdigit():
            filtered_stations = filtered_stations.filter(Q(ls_from_star__lte=int(star_distance)))

        if not include_planetary:
            filtered_stations = filtered_stations.filter(Q(planetary=0))
        if not include_fleet_carriers:
            filtered_stations = filtered_stations.filter(Q(fleet=0))
        if landing_pad_size == "M":
            filtered_stations = filtered_stations.exclude(Q(pad_size='S'))
        elif landing_pad_size == "L":
            filtered_stations = filtered_stations.filter(Q(station__pad_size='L'))


    filtered_stations = filtered_stations[:40]
    if ref_system:
        filtered_stations = filtered_stations.select_related('system')
        distances = {other_station.id: int(other_station.system.distance_to(ref_system)) for other_station in filtered_stations}
        filtered_stations = sorted(list(filtered_stations), key=lambda filtered_station: distances[filtered_station.id], reverse=False)
        if system_distance:
            filtered_stations = filter(lambda filtered_station: distances[filtered_station.id] <= int(system_distance), list(filtered_stations))
        context['reference_distances'] = distances
        context['reference_system'] = ref_system

    context['stations'] = filtered_stations
    context['form'] = form
    return render(request, 'EDSite/station/stations.html', base_context(request) | context)


def station(request, station_id):
    station = Station.objects.get(pk=station_id)
    listings_by_category = {}
    for listing in station.listings.order_by('commodity__name'):
        if listing.commodity.category.name not in listings_by_category:
            listings_by_category[listing.commodity.category.name] = []
        listings_by_category[listing.commodity.category.name].append(listing)
    context = {
        'station': station,
        'listings_by_category': listings_by_category
    }
    return render(request, 'EDSite/station/station.html', base_context(request) | context)


def commodities(request):
    context = {
        'categories': sorted(CommodityCategory.objects.all(),
                             key=lambda category: max(category.commodities.all(), key=lambda com: com.max_profit).max_profit,
                             reverse=True)
    }
    return render(request, 'EDSite/commodity/commodities.html', base_context(request) | context)


def commodity(request, commodity_id):
    commodity = Commodity.objects.get(pk=commodity_id)
    filtered_listings: [LiveListing] = []
    context = {}
    ref_system = None
    ordering = '-demand_price'
    if request.method == 'GET':
        form = CommodityForm()
        form.fields['buy_or_sell'].initial = 'sell'
        form.fields['landing_pad_size'].initial = 'S'
        filtered_listings = LiveListing.objects.filter(commodity_id=commodity_id)
    else:  # POST
        form = CommodityForm(request.POST)
        if form.is_valid():
            include_odyssey = form.data.get('include_odyssey') == 'yes'
            include_fleet_carriers = form.data.get('include_fleet_carriers') == 'yes'
            include_planetary = form.data.get('include_planetary') == 'yes'
            landing_pad_size = form.data.get('landing_pad_size')
            minimum_units = form.data.get('minimum_units') if form.data.get('minimum_units') else 0
            buy_or_sell = form.data.get('buy_or_sell')
            ref_system_name_or_id = form.data.get('reference_system')

            if ref_system_name_or_id and ref_system_name_or_id.isdigit():
                ref_system = System.objects.get(pk=int(ref_system_name_or_id))
                filtered_listings = LiveListing.objects
            elif ref_system_name_or_id:
                ref_system = System.objects.filter(name__icontains=ref_system_name_or_id).first()
                if ref_system:
                    filtered_listings = LiveListing.objects
                else:
                    filtered_listings = LiveListing.objects
            else:
                filtered_listings = LiveListing.objects

            if buy_or_sell == 'sell':
                filtered_listings = LiveListing.objects.filter(commodity_id=commodity_id).filter(Q(demand_units__gt=minimum_units))
            else:
                filtered_listings = LiveListing.objects.filter(commodity_id=commodity_id).filter(Q(supply_units__gt=minimum_units))
            if not include_planetary:
                filtered_listings = filtered_listings.filter(Q(station__planetary=0))
            if not include_fleet_carriers:
                filtered_listings = filtered_listings.filter(Q(station__fleet=0))
            if not include_odyssey:
                filtered_listings = filtered_listings.filter(Q(station__odyssey=0))
            if landing_pad_size == "M":
                filtered_listings = filtered_listings.exclude(Q(station__pad_size='S'))
            elif landing_pad_size == "L":
                filtered_listings = filtered_listings.filter(Q(station__pad_size='L'))
            ordering = '-demand_price' if buy_or_sell == 'sell' else 'supply_price'
        else:
            print("Commodity mission form was not valid:", form.errors)

    filtered_listings = filtered_listings.order_by(ordering)  # TODO: Performance. This makes it slow.
    filtered_listings = filtered_listings[:40]
    if ref_system:
        filtered_listings = filtered_listings.select_related('station__system')
        distances = {listing.id: int(listing.station.system.distance_to(ref_system)) for listing in filtered_listings}
        # filtered_listings = sorted(list(filtered_listings), key=lambda filtered_system: distances[filtered_system.id], reverse=False)
        context['reference_distances'] = distances
        context['reference_system'] = ref_system
    else:
        filtered_listings = filtered_listings.select_related('station__system')

    context['commodity'] = commodity
    context['listings'] = list(filtered_listings)
    context['form'] = form
    return render(request, 'EDSite/commodity/commodity.html', base_context(request) | context)


def rares(request):
    context = {}
    return render(request, 'EDSite/commodity/rares.html', base_context(request) | context)


def carrier_planner(request):
    return redirect("index")


def carrier_missions(request, tab=None):
    base_context_local = base_context(request)
    tab = tab if tab else 'all'
    context = {
        'tab': tab,
        'all_missions': [],
        'my_missions': [],
        'grid_cols': range(3)
    }
    if tab == "all":
        missions: [CarrierMission] = CarrierMission.objects.all()
        context['all_missions'] = list_to_columns(missions, 3)
        context['mission_distances'] = {mission.id: int(mission.station.system.distance_to(CURRENT_SYSTEM)) for mission in missions}

    elif tab == "my":
        # TODO: Show warning if the carrier is not located in the mission system.
        context['my_missions'] = [[1, 2, 3], [1]]
        if request.method == 'GET':
            mission_form = CarrierMissionForm()
            mission_form.fields['worker_profit'].initial = 12000
            mission_form.fields['units'].initial = 15000

            if base_context_local.get('current_user'):
                mission_form.fields['username'].initial = base_context_local.get('current_user').username

            if base_context_local.get('current_carrier'):
                mission_form.fields['carrier_name'].initial = base_context_local.get('current_carrier')[0]

        else:
            mission_form = CarrierMissionForm(request.POST)
            if mission_form.is_valid():
                carrier_name_raw = mission_form.data.get('carrier_name')
                carrier_id = mission_form.data.get('carrier_code')
                username_raw = mission_form.data.get('username')
                station_id = mission_form.data.get('station')
                commodity_id = mission_form.data.get('commodity')
                worker_profit_raw = mission_form.data.get('worker_profit')
                mission_type_raw = mission_form.data.get('mission_type')
                units_raw = mission_form.data.get('units')
                if not station_id or not commodity_id or not carrier_id:
                    print(f"CarrierMissionForm choices are not valid: station_id={station_id}, commodity_id={commodity_id}, carrier_id={carrier_id}")
                else:
                    station = Station.objects.get(pk=station_id)
                    carrier = Station.objects.get(pk=carrier_id)
                    commodity = Commodity.objects.get(pk=commodity_id)
                    current_user = logged_in_user(request)
                    if current_user and commodity and station and carrier:
                        carrier_mission = CarrierMission(
                            user=current_user,
                            mode=mission_type_raw,
                            station=station,
                            carrier=carrier,
                            carrier_name=carrier_name_raw,
                            commodity=commodity,
                            units=units_raw,
                            worker_profit=worker_profit_raw,
                            active=True,
                            date_posted=make_timezone_aware(datetime.datetime.now()),
                            date_completed=None,
                        )
                        carrier_mission.save()
                    else:
                        print("Something was None")
            else:
                print("CarrierMissionForm is not valid:", mission_form.data)
                print(mission_form.errors)
        context['mission_form'] = mission_form

    return render(request, 'EDSite/carrier_missions/carrier_missions_base.html', base_context_local | context)


def trade_routes(request):
    return redirect("index")


@csrf_exempt
def debug_reload(request):
    print("Going to update data.")
    def f():
        EDData().update_tradedangerous_database()
    threading.Thread(target=f).start()
    # EDData().update_tradedangerous_database()
    return JsonResponse({
        "status": EDData().td_database_status.__str__()
    })


@csrf_exempt
def debug_update_database(request, mode='False'):
    update_all = mode == 'all'
    quick = mode == 'quick'
    listings = mode == 'listings'
    cache = mode == 'cache'

    print(f"Updating local database ({mode})...")
    def f():
        EDData().update_local_database(data=update_all,
                                       update_stations=update_all or quick,
                                       update_systems=update_all or quick,
                                       update_commodities=update_all or quick,
                                       update_listings=update_all or listings,
                                       update_cache=update_all or listings or cache,
                                       full_listings_update=True,
                                       )
    threading.Thread(target=f).start()

    return JsonResponse({
        "status": "No status"
    })


def signup_view(request):
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            # user = form.save()
            username = form.cleaned_data.get('username')
            password1 = form.cleaned_data.get('password1')
            password2 = form.cleaned_data.get('password2')
            email = form.cleaned_data.get('email')
            messages.success(request, "Registration successful.")
            user = form.save()# authenticate(username=username, password=password1, email=email)
            login(request, user)
            return redirect("index")
        messages.error(request, "Unsuccessful registration. Invalid information.")
    else:
        form = SignupForm()
    return render(request=request, template_name="EDSite/account/signup.html", context=base_context(request) | {"signup_form": form})


def login_view(request):
    if request.method == "POST":
        form = LoginForm(request, request.POST)
        if form.is_valid() or True:
            username = form.cleaned_data.get('username')
            # email = form.cleaned_data.get('email')
            password = form.cleaned_data.get('password')
            user = authenticate(request, username=username, password=password)
            if user is not None:
                messages.success(request, "login successful.")
                login(request, user)
                return redirect("index")
            else:
                # Return an 'invalid login' error message.
                messages.error(request, "Unsuccessful login. Invalid information.")
        else:
            print('Valid:', form.is_valid(), form.errors)
            messages.error(request, "Unsuccessful login. Invalid information.")
    else:
        form = LoginForm()
    return render(request=request, template_name="EDSite/account/login.html", context=base_context(request) | {"login_form": form})


# @login_required
def profile_view(request):
    return redirect("index")


def logout_view(request):
    logout(request)
    return redirect("index")

