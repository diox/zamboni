from django.db import IntegrityError
from django.utils.datastructures import MultiValueDictKeyError

from rest_framework import exceptions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from mkt.api.authentication import (RestOAuthAuthentication,
                                    RestAnonymousAuthentication)
from mkt.api.base import CORSViewSet
from mkt.webapps.models import Webapp

from .authorization import PublisherAuthorization
from .constants import COLLECTIONS_TYPE_BASIC
from .models import Collection, Page
from .serializers import CollectionSerializer, PageSerializer


class CollectionViewSet(CORSViewSet, viewsets.ModelViewSet):
    serializer_class = CollectionSerializer
    queryset = Collection.objects.all()
    cors_allowed_methods = ('get', 'post')
    permission_classes = [PublisherAuthorization]
    authentication_classes = [RestOAuthAuthentication,
                              RestAnonymousAuthentication]

    collection_type = COLLECTIONS_TYPE_BASIC

    def return_updated(self, status):
        """
        Passed an HTTP status from rest_framework.status, returns a response
        of that status with the body containing the updated values of
        self.object.
        """
        collection = self.get_object()
        serializer = self.get_serializer(instance=collection)
        return Response(serializer.data, status=status)

    def pre_save(self, obj):
        """
        Allow subclasses of CollectionViewSet to create collections of different
        `collection_type`s by changing the class' `collection_type` property.
        """
        obj.collection_type = self.collection_type
        super(CollectionViewSet, self).pre_save(obj)

    @action()
    def add_app(self, request, pk=None):
        """
        Add an app to the specified collection.
        """
        collection = self.get_object()
        try:
            new_app = Webapp.objects.get(pk=request.DATA['app'])
        except MultiValueDictKeyError:
            raise exceptions.ParseError(detail='`app` was not provided.')
        except Webapp.DoesNotExist:
            raise exceptions.ParseError(detail='`app` does not exist.')
        try:
            collection.add_app(new_app)
        except IntegrityError:
            raise exceptions.ParseError(
                detail='`app` already exists in collection.')
        return self.return_updated(status.HTTP_201_CREATED)


class PageViewSet(viewsets.ModelViewSet):
    serializer_class = PageSerializer
    queryset = Page.objects.all()
    permission_classes = [PublisherAuthorization]  # FIXME
    authentication_classes = [RestOAuthAuthentication,
                              RestAnonymousAuthentication]

    collection_type = COLLECTIONS_TYPE_BASIC

    @action()
    def add_collection(self, request, pk=None):
        """
        Add an collection to the specified page.
        """
        page = self.get_object()
        try:
            collection_id = request.DATA['collection']
            new_collection = Collection.objects.get(pk=collection_id)
        except MultiValueDictKeyError:
            raise exceptions.ParseError(
                detail='`collection` was not provided.')
        except Collection.DoesNotExist:
            raise exceptions.ParseError(detail='`collection` does not exist.')
        try:
            page.add_collection(new_collection)
        except IntegrityError:
            raise exceptions.ParseError(
                detail='`collection` already exists in page.')

        # Return the page object.
        serializer = self.get_serializer(instance=page)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
