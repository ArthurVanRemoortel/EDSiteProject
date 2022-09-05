from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path, include, re_path
from rest_framework import routers

from . import views
from . import views_api

router = routers.DefaultRouter()
router.register('commodities', views_api.CommoditiesViewSet, basename="api-commodities")
router.register('listings', views_api.ListingsViewSet, basename="api-listings")

urlpatterns = [
    path('api/', include(router.urls)),

    path('', views.index, name='index'),
    path('systems', views.systems, name='systems'),
    path('stations', views.stations, name='stations'),
    path('stations/<int:station_id>', views.station, name='station'),
    path('systems/<int:system_id>', views.system, name='system'),
    path('commodities', views.commodities, name='commodities'),
    path('commodities/<int:commodity_id>', views.commodity, name='commodity'),
    path('rares', views.rares, name='rares'),

    path('debug_reload', views.debug_reload, name='debug_reload'),
    path('debug_update_database<str:mode>', views.debug_update_database, name='debug_update_database'),

    path("signup", views.signup_view, name="signup"),
    path("login", views.login_view, name="login"),

    path("profile", views.profile_view, name="profile"),
    path("logout", views.logout_view, name="logout"),

    path("trade/trade-routes", views.trade_routes, name="trade-routes"),
    path("trade/carrier-missions", views.carrier_missions, name="carrier-missions"),
    path("trade/carrier-missions/<str:tab>", views.carrier_missions, name="carrier-missions"),

    # path('api/commodities', views_api.api_commodities, name="api_commodities")
]

urlpatterns += staticfiles_urlpatterns()