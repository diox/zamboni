from django.db.models import Max


def next_order_value(cls, **filters):
    qs = cls.objects.filter(**filters)
    aggregate = qs.aggregate(Max('order'))['order__max']
    return aggregate + 1 if aggregate else 1
