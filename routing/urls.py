from django.urls import path

from .views import RoutePlanView, map_view

urlpatterns = [
    path("route/", RoutePlanView.as_view(), name="route-plan"),
    path("map/", map_view, name="route-map"),
]
