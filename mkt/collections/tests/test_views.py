import json

from django.core.urlresolvers import reverse

from nose.tools import eq_

import amo.tests
from mkt.api.tests.test_oauth import RestOAuth
from mkt.collections.constants import (COLLECTIONS_TYPE_BASIC,
                                       PAGE_TYPE_HOMESCREEN, 
                                       PAGE_TYPE_OPERATORSHELF)  
from mkt.collections.models import Collection, Page
from mkt.collections.serializers import CollectionSerializer, PageSerializer
from mkt.site.fixtures import fixture


class TestCollectionViewSet(RestOAuth, amo.tests.TestCase):
    fixtures = fixture('user_2519')

    def setUp(self):
        self.create_switch('rocketfuel')
        super(TestCollectionViewSet, self).setUp()
        self.serializer = CollectionSerializer()
        self.collection_data = {
            'name': 'My Favorite Games',
            'description': 'A collection of my favorite games'
        }
        self.collection = Collection.objects.create(**self.collection_data)
        self.apps = [amo.tests.app_factory() for n in xrange(1, 5)]
        self.list_url = reverse('collections-list')

    def listing(self, client):
        for app in self.apps:
            self.collection.add_app(app)
        res = client.get(self.list_url)
        data = json.loads(res.content)
        eq_(res.status_code, 200)
        eq_(data['objects'][0]['apps'], self.collection.app_urls())

    def test_listing(self):
        self.listing(self.anon)

    def test_listing_no_perms(self):
        self.listing(self.client)

    def test_listing_has_perms(self):
        self.grant_permission(self.profile, 'Apps:Publisher')
        self.listing(self.client)

    def create(self, client):
        res = client.post(self.list_url, json.dumps(self.collection_data))
        data = json.loads(res.content)
        return res, data

    def test_create_anon(self):
        res, data = self.create(self.anon)
        eq_(res.status_code, 403)

    def test_create_no_perms(self):
        res, data = self.create(self.client)
        eq_(res.status_code, 403)

    def test_create_has_perms(self):
        self.grant_permission(self.profile, 'Apps:Publisher')
        res, data = self.create(self.client)
        eq_(res.status_code, 201)

    def add_app(self, client, app=None):
        if not app:
            app = self.apps[0]
        url = reverse('collections-add-app', kwargs={'pk': self.collection.pk})
        res = client.post(url, json.dumps({'app': app.pk}))
        data = json.loads(res.content)
        return res, data

    def test_add_app_anon(self):
        res, data = self.add_app(self.anon)
        eq_(res.status_code, 403)

    def test_add_app_no_perms(self):
        res, data = self.add_app(self.client)
        eq_(res.status_code, 403)

    def test_add_app_has_perms(self):
        self.grant_permission(self.profile, 'Apps:Publisher')
        res, data = self.add_app(self.client)
        eq_(res.status_code, 201)
        self.assertSetEqual(self.collection.apps(), [self.apps[0]])
        res, data = self.add_app(self.client, self.apps[2])
        eq_(res.status_code, 201)
        self.assertSetEqual(self.collection.apps(), [self.apps[0],
                                                     self.apps[2]])


class TestPageViewSet(RestOAuth, amo.tests.TestCase):
    fixtures = fixture('user_2519')

    def setUp(self):
        self.create_switch('rocketfuel')
        super(TestPageViewSet, self).setUp()
        self.serializer = PageSerializer()
        self.page_data = {
            'page_type': PAGE_TYPE_HOMESCREEN
        }
        self.page = Page.objects.create(**self.page_data)
        self.list_url = reverse('pages-list')
        self.create_data()

    def create_data(self):
        self.collections = [
            Collection.objects.create(name='A Basic Collection',
              description='Awesome apps!',
              collection_type=COLLECTIONS_TYPE_BASIC),
            Collection.objects.create(name='Another Basic Collection',
              description='Even More Awesome Apps!',
              collection_type=COLLECTIONS_TYPE_BASIC)
        ]

        for collection in self.collections:
            for n in xrange(1, 3):
                collection.add_app(amo.tests.app_factory())
            self.page.add_collection(collection)

    def listing(self, client):
        res = client.get(self.list_url)
        data = json.loads(res.content)
        eq_(res.status_code, 200)
        eq_(data['objects'][0]['collections'], self.page.collection_urls())

    def test_listing(self):
        self.listing(self.anon)

    def test_listing_no_perms(self):
        self.listing(self.client)

    def test_listing_has_perms(self):
        self.grant_permission(self.profile, 'Apps:Publisher')
        self.listing(self.client)

    def create(self, client):
        res = client.post(self.list_url, json.dumps({
            'page_type': PAGE_TYPE_OPERATORSHELF
        }))
        data = json.loads(res.content)
        return res, data

    def test_create_anon(self):
        res, data = self.create(self.anon)
        eq_(res.status_code, 403)

    def test_create_no_perms(self):
        res, data = self.create(self.client)
        eq_(res.status_code, 403)

    def test_create_has_perms(self):
        self.grant_permission(self.profile, 'Apps:Publisher')
        res, data = self.create(self.client)
        eq_(res.status_code, 201)

    def add_collection(self, client):
        self.extra_collection = collection = Collection.objects.create(
            name='A third Basic Collection',
            description='Third Description',
            collection_type=COLLECTIONS_TYPE_BASIC)
        collection.add_app(amo.tests.app_factory())

        url = reverse('pages-add-collection', kwargs={'pk': self.page.pk})
        res = client.post(url, json.dumps({'collection': collection.pk}))
        data = json.loads(res.content)
        return res, data

    def test_add_collection_anon(self):
        res, data = self.add_collection(self.anon)
        eq_(res.status_code, 403)

    def test_add_collection_no_perms(self):
        res, data = self.add_collection(self.client)
        eq_(res.status_code, 403)

    def test_add_collection_has_perms(self):
        self.grant_permission(self.profile, 'Apps:Publisher')
        res, data = self.add_collection(self.client)
        eq_(res.status_code, 201)
        self.assertSetEqual(self.page.get_collections(),
            [self.collections[0], self.collections[1], self.extra_collection])
