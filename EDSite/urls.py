from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('systems', views.systems, name='systems'),
    path('stations', views.stations, name='stations'),
    path('stations/<int:station_id>', views.station, name='station'),
    path('commodities', views.commodities, name='commodities'),
    path('commodities/<int:item_id>', views.commodity, name='commodity'),
    path('rares', views.rares, name='rares'),

    path('debug_reload', views.debug_reload, name='debug_reload'),
    path('debug_update_database<str:mode>', views.debug_update_database, name='debug_update_database'),

    path("signup", views.signup_view, name="signup"),
    path("login", views.login_view, name="login"),

    path("profile", views.profile_view, name="profile"),
    path("logout", views.logout_view, name="logout"),

    path("planners/trade-routes", views.trade_routes, name="trade-routes"),
    path("planners/carrier-planner", views.carrier_planner, name="carrier-planner"),
    path("planners/carrier-missions", views.carrier_missions, name="carrier-missions"),
]