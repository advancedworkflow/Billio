"""
Filters which endpoints appear in the public API schema/docs (/api/).

Billio's DRF layer also backs internal HTMX/dashboard views and webhooks that
were never meant to be a documented public surface. This hook keeps only the
core business ViewSets we're deliberately exposing to integrations.
"""


def public_api_endpoints(endpoints):
    from apps.invoices.views import InvoiceViewSet, QuoteViewSet
    from apps.clients.views import ClientViewSet
    from apps.payments.views import PaymentViewSet, PaymentMethodViewSet

    allowed_viewsets = {
        InvoiceViewSet, QuoteViewSet, ClientViewSet,
        PaymentViewSet, PaymentMethodViewSet,
    }

    return [
        (path, path_regex, method, callback)
        for path, path_regex, method, callback in endpoints
        if getattr(callback, 'cls', None) in allowed_viewsets
    ]
