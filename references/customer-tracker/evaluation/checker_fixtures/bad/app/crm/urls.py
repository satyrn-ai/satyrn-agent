from django.urls import path as route
from django.views.generic import View as BaseView

urlpatterns = [route("", BaseView.as_view())]
