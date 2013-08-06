from tower import ugettext_lazy as _lazy


COLLECTIONS_TYPE_BASIC = 0
COLLECTIONS_TYPE_FEATURED = 1
COLLECTIONS_TYPE_OPERATOR = 2

COLLECTION_TYPES = (
    (COLLECTIONS_TYPE_BASIC, _lazy(u'Basic Collection')),
    (COLLECTIONS_TYPE_FEATURED, _lazy(u'Featured App List')),
    (COLLECTIONS_TYPE_OPERATOR, _lazy(u'Operator Shelf')),
)

PAGE_TYPE_HOMESCREEN = 0
PAGE_TYPE_OPERATORSHELF = 1
PAGE_TYPE_CATEGORY = 2

PAGE_TYPES = (
    (PAGE_TYPE_HOMESCREEN, _lazy(u'Homescreen')),
    (PAGE_TYPE_OPERATORSHELF, _lazy(u'Operator Shelf')),
    (PAGE_TYPE_CATEGORY, _lazy(u'Category')),
)