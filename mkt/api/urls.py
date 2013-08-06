from django.conf import settings
from django.conf.urls import include, patterns, url

from rest_framework.routers import SimpleRouter
from tastypie.api import Api
from tastypie_services.services import (ErrorResource, SettingsResource)

from mkt.submit.api import PreviewResource, StatusResource, ValidationResource
from mkt.api.base import AppRouter, handle_500, SlugRouter
from mkt.api.resources import (AppResource, CarrierResource, CategoryViewSet,
                               ConfigResource, error_reporter,
                               RefreshManifestViewSet, RegionResource)
from mkt.collections.views import CollectionViewSet, PageViewSet
from mkt.features.views import AppFeaturesList
from mkt.stats.api import GlobalStatsResource
from mkt.ratings.resources import RatingResource
from mkt.search.api import SearchResource, SuggestionsResource


api = Api(api_name='apps')
api.register(ValidationResource())
api.register(AppResource())
api.register(PreviewResource())
api.register(SearchResource())
api.register(SuggestionsResource())
api.register(StatusResource())
api.register(RatingResource())


rocketfuel = SimpleRouter()
rocketfuel.register(r'collections', CollectionViewSet,
                    base_name='collections')
rocketfuel.register(r'pages', PageViewSet,
                    base_name='pages')

apps = SlugRouter()
apps.register(r'category', CategoryViewSet, base_name='app-category')
subapps = AppRouter()
subapps.register('refresh-manifest', RefreshManifestViewSet,
                 base_name='app-refresh-manifest')

stats_api = Api(api_name='stats')
stats_api.register(GlobalStatsResource())

services = Api(api_name='services')
services.register(ConfigResource())
services.register(RegionResource())
services.register(CarrierResource())

if settings.ALLOW_TASTYPIE_SERVICES:
    services.register(ErrorResource(set_handler=handle_500))
    if getattr(settings, 'CLEANSED_SETTINGS_ACCESS', False):
        services.register(SettingsResource())

urlpatterns = patterns('',
    url(r'^', include(api.urls)),
    url(r'^apps/', include(apps.urls)),
    url(r'^apps/app/', include(subapps.urls)),
    url(r'^', include(stats_api.urls)),
    url(r'^', include(services.urls)),
    url(r'^fireplace/report_error', error_reporter, name='error-reporter'),
    url(r'^rocketfuel/', include(rocketfuel.urls)),
    url(r'^apps/', include('mkt.versions.urls')),
    url(r'^apps/features/', AppFeaturesList.as_view(),
        name='api-features-feature-list')
)
