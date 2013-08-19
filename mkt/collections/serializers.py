from rest_framework import serializers
from tower import ugettext_lazy as _

from mkt.webapps.utils import app_to_dict

from .models import Collection
from .constants import COLLECTIONS_TYPE_FEATURED, COLLECTIONS_TYPE_OPERATOR


class CollectionMembershipField(serializers.RelatedField):
    def to_native(self, value):
        return app_to_dict(value.app)


class CollectionSerializer(serializers.ModelSerializer):
    name = serializers.CharField()
    description = serializers.CharField()
    collection_type = serializers.IntegerField()
    apps = CollectionMembershipField(many=True,
                                     source='collectionmembership_set')

    class Meta:
        fields = ('apps', 'author', 'carrier', 'category', 'collection_type',
                  'description', 'id', 'is_public', 'name', 'region',)
        model = Collection

    def full_clean(self, instance):
        instance = super(CollectionSerializer, self).full_clean(instance)
        # For featured apps and operator shelf collections, we need to check if
        # one already exists for the same region/category/carrier combination.
        #
        # Sadly, this can't be expressed as a db-level unique constaint,
        # because this doesn't apply to basic collections.

        # We have to do it  ourselves, and we need the rest of the validation
        # to have already taken place, and have the incoming data and original
        # data from existing instance if it's an edit, so full_clean() is the
        # best place to do it.
        unique_collections_types = (COLLECTIONS_TYPE_FEATURED,
                                    COLLECTIONS_TYPE_OPERATOR)
        if (instance.collection_type in unique_collections_types and
            Collection.objects.filter(collection_type=instance.collection_type,
                                      category=instance.category,
                                      region=instance.region,
                                      carrier=instance.carrier).exists()):
            self._errors['collection_uniqueness'] = _(
                u'Featured Apps and Operator Shelf collections must be unique'
                u' for a given category, carrier, region and type combination')
        return instance
