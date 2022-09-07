import datetime
import threading
import time
from pprint import pprint

from django.contrib import messages
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db.models import Q, Count
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

CURRENT_SYSTEM = System.objects.get(name="Sol")  # Sol system
if settings.LIVE_UPDATER:
    print('Starting the live listener.')
    threading.Thread(target=EDData().start_live_listener).start()
else:
    print('Not starting the live listener.')


def logged_in_user(request):
    return request.user if not request.user.is_anonymous else None


def base_context(request) -> {}:
    return {
        'current_user': logged_in_user(request),
        'current_system': CURRENT_SYSTEM,
        'current_carrier': ('Normandy SR-404', 'K7Q-BQL'),
        'DEBUG_MODE': settings.DEBUG_MODE
    }


def index(request):
    context = {}
    return render(request, 'EDSite/index.html', base_context(request) | context)


def systems(request):
    context = {}
    if request.method == 'GET':
        form = SystemsForm()
        form.fields['only_populated'].initial = 'no'
        filtered_systems = System.objects.order_by('id')
        mission_distances = {}
    else:
        form = SystemsForm(request.POST)
        search = form.data['search']
        ref_system_name_or_id = form.data['reference_system']
        ref_system = None
        if ref_system_name_or_id and ref_system_name_or_id.isdigit():
            ref_system = System.objects.get(pk=int(ref_system_name_or_id))
        elif ref_system_name_or_id:
            ref_system = System.objects.filter(name__icontains=ref_system_name_or_id).order_by('id').first()

        only_populated = form.data['only_populated'] == 'yes'
        if search:
            filtered_systems = System.objects.filter(name__icontains=search).order_by('id')
        else:
            filtered_systems = System.objects.all().order_by('id')
        if only_populated:
            filtered_systems = filtered_systems.annotate(num_stations=Count('stations')).filter(num_stations__gt=0)

    # context['reference_distances'] = {mission.id: int(mission.station.system.distance_to(CURRENT_SYSTEM)) for mission in missions}
    context['systems'] = filtered_systems[:40]
    context['form'] = form
    return render(request, 'EDSite/systems.html', base_context(request) | context)


def system(request, system_id):
    context = {
        'system': System.objects.get(pk=system_id),
    }
    return render(request, 'EDSite/system.html', base_context(request) | context)


def stations(request):
    context = {}
    if request.method == 'GET':
        form = StationsForm()
        context['stations'] = Station.objects.order_by('id')[:40]
    else:
        form = StationsForm(request.POST)
        search = form.data['search']
        ref_system_name = form.data['reference_system']
        include_fleet_carriers = form.data['include_fleet_carriers'] == 'yes'
        include_planetary = form.data['include_planetary'] == 'yes'
        landing_pad_size = form.data['landing_pad_size']
        star_distance = form.data['star_distance']
        system_distance = form.data['system_distance']

        if search:
            filtered_stations = Station.objects.filter(name__icontains=search).order_by('id')
        else:
            filtered_stations = Station.objects.order_by('id').all()
        if not include_planetary:
            filtered_stations = filtered_stations.filter(Q(planetary=0))
        if not include_fleet_carriers:
            filtered_stations = filtered_stations.filter(Q(fleet=0))
        if landing_pad_size == "M":
            filtered_stations = filtered_stations.exclude(Q(pad_size='S'))
        elif landing_pad_size == "L":
            filtered_stations = filtered_stations.filter(Q(station__pad_size='L'))

        # TODO: Add star_distance and system_distance filter.

        context['stations'] = filtered_stations[:40]
    context['form'] = form
    return render(request, 'EDSite/stations.html', base_context(request) | context)


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
    return render(request, 'EDSite/station.html', base_context(request) | context)


def commodities(request):
    context = {
        'categories': CommodityCategory.objects.all(),
    }
    return render(request, 'EDSite/commodities.html', base_context(request) | context)


def commodity(request, commodity_id):
    commodity = Commodity.objects.get(pk=commodity_id)
    listings: [LiveListing] = []
    t0 = time.time()

    if request.method == 'GET':
        form = CommodityForm()
        form.fields['buy_or_sell'].initial = 'sell'
        form.fields['landing_pad_size'].initial = 'S'
        listings = LiveListing.objects.filter(commodity_id=commodity_id).order_by('-demand_price')
    else:  # POST
        form = CommodityForm(request.POST)
        if form.is_valid():
            ref_system_name = form.data['reference_system']
            include_odyssey = form.data['include_odyssey'] == 'yes'
            include_fleet_carriers = form.data['include_fleet_carriers'] == 'yes'
            include_planetary = form.data['include_planetary'] == 'yes'
            landing_pad_size = form.data['landing_pad_size']
            minimum_units = form.data['minimum_units'] if form.data['minimum_units'] else 0
            buy_or_sell = form.data['buy_or_sell']
            if buy_or_sell == 'sell':
                listings = LiveListing.objects.filter(commodity_id=commodity_id).filter(Q(demand_units__gt=minimum_units))
            else:
                listings = LiveListing.objects.filter(commodity_id=commodity_id).filter(Q(supply_units__gt=minimum_units))
            if not include_planetary:
                listings = listings.filter(Q(station__planetary=0))
            if not include_fleet_carriers:
                listings = listings.filter(Q(station__fleet=0))
            if not include_odyssey:
                listings = listings.filter(Q(station__odyssey=0))
            if landing_pad_size == "M":
                listings = listings.exclude(Q(station__pad_size='S'))
            elif landing_pad_size == "L":
                listings = listings.filter(Q(station__pad_size='L'))
            listings = listings.order_by('-demand_price' if buy_or_sell == 'sell' else 'supply_price')

    context = {
        'commodity': commodity,
        'listings': list(listings[:40]),
        'form': form
    }
    return render(request, 'EDSite/commodity.html', base_context(request) | context)


def rares(request):
    context = {}
    return render(request, 'EDSite/rares.html', base_context(request) | context)


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
        context['my_missions'] = [[1, 2, 3], [1]]
        if request.method == 'GET':
            mission_form = CarrierMissionForm()
            if base_context_local['current_carrier']:
                mission_form.fields['carrier_name'].initial = base_context_local['current_carrier'][0]
                mission_form.fields['carrier_code'].initial = base_context_local['current_carrier'][1]
            if base_context_local['current_user']:
                mission_form.fields['username'].initial = base_context_local['current_user'].username
            if base_context_local['current_system']:
                system: System = base_context_local['current_system']
                mission_form.fields['system'].initial = system.name

            mission_form.fields['system'].initial = "Ba Po"
            mission_form.fields['station'].initial = "Lewitt Works"
            mission_form.fields['commodity'].initial = "Bauxite"
            mission_form.fields['worker_profit'].initial = 12000
            mission_form.fields['units'].initial = 15000

        else:
            mission_form = CarrierMissionForm(request.POST)
            if mission_form.is_valid():
                carrier_name_raw = mission_form.data['carrier_name']
                carrier_code_raw = mission_form.data['carrier_code']
                username_raw = mission_form.data['username']
                system_raw = mission_form.data['system']
                station_raw = mission_form.data['station']
                commodity_raw = mission_form.data['commodity']
                worker_profit_raw = mission_form.data['worker_profit']
                mission_type_raw = mission_form.data['mission_type']
                units_raw = mission_form.data['units']

                station = Station.objects.get(Q(name=station_raw) & Q(system__name=system_raw))
                carrier = Station.objects.get(Q(name=carrier_code_raw))
                commodity = Commodity.objects.get(name=commodity_raw)
                current_user = logged_in_user(request)

                if current_user and commodity and station:
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
        EDData().update_local_database(data=update_all or quick,
                                       update_stations=update_all or quick,
                                       update_systems=update_all or quick,
                                       update_commodities=update_all or quick,
                                       update_listings=update_all or listings or quick,
                                       update_cache=update_all or listings or cache or quick,
                                       full_listings_update=not quick,
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

