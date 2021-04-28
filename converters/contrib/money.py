from django.conf import settings

from moneyed import Money
from pydash import get

from ..converter import _SENTRY


def currency_converter_for_field(field, fallback_currency_field=None):
    def currency_converter(src):
        amount = get(src, field, _SENTRY)
        if isinstance(amount, Money):
            return amount

        currency = get(src, f'{field}_currency')
        if amount is None or amount is _SENTRY:
            # no amount passed
            return amount

        if currency is None:
            currency = (
                get(src, fallback_currency_field) or settings.HOME_CURRENCY
                if fallback_currency_field
                else settings.HOME_CURRENCY
            )

        return Money(amount, currency)

    return currency_converter
