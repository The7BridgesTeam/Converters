import logging
import re

from django.conf import settings

from django_countries import countries
from django_countries.fields import Country as DJCountry

from ..converter import Converter


log = logging.getLogger(__name__)


def _country_name_normalizer(country_name):
    return re.sub(r'\s+', ' ', country_name.lower().strip())


def _populate_country_mapping():
    country_name_to_code = {_country_name_normalizer(name): code for code, name in countries}

    country_name_to_code.update(
        {
            _country_name_normalizer(alpha3): code
            for code, (alpha3, _) in countries.alt_codes.items()
        }
    )

    for code, alias_names in getattr(settings, 'COUNTRY_ALIASES', {}).items():
        for alias in alias_names:
            country_name_to_code[_country_name_normalizer(alias)] = code

    return country_name_to_code


COUNTRY_NORMALIZED_NAME_TO_CODE_MAP = _populate_country_mapping()


def convert_to_country_code(country_name):
    if country_name is None:
        return ''

    if isinstance(country_name, DJCountry):
        return country_name.code

    if not isinstance(country_name, str):
        raise TypeError(f'Invalid type for country name: {type(country_name)}')

    normalized_name = _country_name_normalizer(country_name)

    if not normalized_name:
        return ''

    if normalized_name.upper() in COUNTRY_NORMALIZED_NAME_TO_CODE_MAP.values():
        # It's a country code already
        return normalized_name.upper()

    code_from_name = COUNTRY_NORMALIZED_NAME_TO_CODE_MAP.get(normalized_name)
    if code_from_name is not None:
        return code_from_name.upper()

    log.warning('Could not determine country code of %r', country_name)

    return ''


Converter.register_converter_for_name(convert_to_country_code, 'country_code')
