from rest_framework import serializers

from .models import Collection, Page


class CollectionSerializer(serializers.ModelSerializer):
    name = serializers.CharField()
    description = serializers.CharField()
    collection_type = serializers.IntegerField(default=0)

    class Meta:
        fields = ('name', 'description', 'id',)
        model = Collection

    def to_native(self, obj):
        native = super(CollectionSerializer, self).to_native(obj)
        native['apps'] = obj.app_urls()
        return native


class PageSerializer(serializers.ModelSerializer):
    region = serializers.IntegerField(default=0)
    page_type = serializers.IntegerField(default=0)

    class Meta:
        fields = ('region', 'page_type', 'id',)
        model = Page

    def to_native(self, obj):
        native = super(PageSerializer, self).to_native(obj)
        native['collections'] = obj.collection_urls()
        return native