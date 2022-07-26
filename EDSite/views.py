from pprint import pprint

from django.contrib import messages
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import AnonymousUser
from django.core import cache
from django.db.models import Q
from django.http import HttpResponse, JsonResponse, HttpResponseRedirect
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt

# import EDSite.ed_data
from EDSite.ed_data import EDData
from EDSite.forms import CommodityForm, SignupForm, LoginForm
from EDSite.models import CommodityCategory, Commodity, Station, LiveListing


def base_context(request) -> {}:
    return {
        'current_user': request.user if not request.user.is_anonymous else None
    }


def index(request):
    context = {}
    return render(request, 'EDSite/index.html', base_context(request) | context)


def systems(request):
    context = {}
    return render(request, 'EDSite/systems.html', base_context(request) | context)


def stations(request):
    context = {}
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
    # pprint(context['categories'][0].commodities.all())
    return render(request, 'EDSite/commodities.html', base_context(request) | context)


def commodity(request, item_id):
    commodity = Commodity.objects.get(pk=item_id)
    # pprint(EDData().test(commodity_id=commodity.id))
    listings: [LiveListing] = []
    if request.method == 'GET':
        form = CommodityForm()
        form.fields['buy_or_sell'].initial = 'sell'
        form.fields['landing_pad_size'].initial = 'S'
        listings = LiveListing.objects.filter(commodity_id=item_id).filter(Q(demand_units__gt=0)).order_by('-demand_price')[:30]
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
                listings = LiveListing.objects.filter(commodity_id=item_id).filter(Q(demand_units__gt=minimum_units))
            else:
                listings = LiveListing.objects.filter(commodity_id=item_id).filter(Q(supply_units__gt=minimum_units))
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
            listings = listings[:30]
        else:
            raise Exception()
    context = {
        'commodity': commodity,
        'listings': listings,
        'form': form
    }
    return render(request, 'EDSite/commodity.html', base_context(request) | context)


def rares(request):
    context = {}
    return render(request, 'EDSite/rares.html', base_context(request) | context)


@csrf_exempt
def debug_reload(request):
    print("Going to update data.")
    EDData().update_tradedangerous_database()
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
    EDData().update_local_database(update_stations=update_all,
                                   update_systems=update_all,
                                   update_commodities=update_all or quick,
                                   update_listings=update_all or listings,
                                   update_cache=update_all or listings or cache
                                   )
    return JsonResponse({
        "status": "No status"
    })


def signup_view(request):
    if request.method == "POST":
        form = SignupForm(request, request.POST)
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
        pprint(request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            email = form.cleaned_data.get('email')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            messages.success(request, "login successful.")
            login(request, user)
            return redirect("index")
        else:
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


def carrier_planner(request):
    return redirect("index")


def carrier_missions(request):
    return redirect("index")


def trade_routes(request):
    return redirect("index")
