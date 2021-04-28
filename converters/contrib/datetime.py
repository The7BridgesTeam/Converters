from dateutil import parser
from pytz import timezone

from ..converter import Converter

__all__ = [
    'convert_str_to_datetime',
    'convert_str_to_naive_datetime',
    'convert_naive_str_to_utc_datetime',
    'convert_str_to_time',
    'exports',
]


def convert_str_to_datetime(str_):
    return parser.parse(str_)


def convert_str_to_naive_datetime(str_):
    return parser.parse(str_, ignoretz=True)


def convert_naive_str_to_utc_datetime(str_):
    naive_dt = convert_str_to_naive_datetime(str_)
    return timezone('utc').localize(naive_dt)


def convert_str_to_time(str_):
    return convert_str_to_datetime(str_).time()


for func, name in [
    (convert_str_to_datetime, 'datetime'),
    (convert_str_to_time, 'time'),
    (convert_str_to_naive_datetime, 'datetime_naive'),
    (convert_naive_str_to_utc_datetime, 'datetime_naive_to_utc'),
]:
    Converter.register_converter_for_name(func, name)

exports = __all__
