from django.core.urlresolvers import reverse
from django.db import models

import amo.models
import mkt.regions
from addons.models import Category
from mkt.webapps.models import Webapp
from translations.fields import PurifiedField, save_signal

from .constants import COLLECTION_TYPES, PAGE_TYPES
from .utils import next_order_value


class Collection(amo.models.ModelBase):
    collection_type = models.IntegerField(choices=COLLECTION_TYPES, null=True)
    description = PurifiedField()
    name = PurifiedField()

    class Meta:
        db_table = 'app_collections'

    def __unicode__(self):
        return self.name.localized_string_clean

    def apps(self):
        """
        Return a list containing all apps in this collection.
        """
        return [a.app for a in self.collectionmembership_set.all()]

    def app_urls(self):
        """
        Returns a list of URLs of all apps in this collection.
        """
        return [reverse('api_dispatch_detail', kwargs={
            'resource_name': 'app',
            'api_name': 'apps',
            'pk': a.pk
        }) for a in self.apps()]

    def add_app(self, app, order=None):
        """
        Add an app to this collection. If specified, the app will be created
        with the specified `order`. If not, it will be added to the end of the
        collection.
        """
        if not order:
            order = next_order_value(CollectionMembership, collection=self)
        return CollectionMembership.objects.create(collection=self, app=app,
                                                   order=order)


class CollectionMembership(amo.models.ModelBase):
    collection = models.ForeignKey(Collection)
    app = models.ForeignKey(Webapp)
    order = models.SmallIntegerField(null=True)

    def __unicode__(self):
        return u'"%s" in "%s"' % (self.app.name,
                                  self.collection.name)

    class Meta:
        db_table = 'app_collection_membership'
        unique_together = ('collection', 'app',)
        ordering = ('order',)


models.signals.pre_save.connect(save_signal, sender=Collection,
                                dispatch_uid='collection_translations')


class Page(amo.models.ModelBase):
    region = models.PositiveIntegerField(default=mkt.regions.WORLDWIDE.id,
                                         db_index=True)
    page_type = models.IntegerField(choices=PAGE_TYPES)
    Category = models.ForeignKey(Category, null=True)  # FIXME: only when page_type == PAGE_TYPE_CATEGORY
    featured = models.ForeignKey(Collection, null=True, related_name='featured_pages')  # FIXME: limit to Collections with collection_type == COLLECTIONS_TYPE_FEATURED
    collections = models.ManyToManyField(Collection, through='PageCollection')

    class Meta:
        unique_together = ('region', 'page_type')

    def __unicode__(self):
        region_name = mkt.regions.REGIONS_CHOICES_ID_DICT[self.region].name
        return u'%s Page for %s' % (self.get_page_type_display(), unicode(region_name))

    def get_collections(self):
        return [c.collection for c in self.pagecollection_set.all()]

    def collection_urls(self):
        """
        Returns a list of URLs of all collections in this page.
        """
        return [reverse('collections-detail', kwargs={
            'pk': pc.collection.pk
        }) for pc in self.pagecollection_set.all()]

    def add_collection(self, collection, order=None):
        if not order:
            order = next_order_value(PageCollection, page=self)
        return PageCollection.objects.create(page=self, collection=collection,
                                             order=order)


class PageCollection(amo.models.ModelBase):
    page = models.ForeignKey(Page)
    collection = models.ForeignKey(Collection)
    order = models.SmallIntegerField(null=True)

    def __unicode__(self):
        return u'"%s" Collection in "%s"' % (self.collection.name, self.page)

    class Meta:
        unique_together = ('page', 'collection',)
        ordering = ('order',)
