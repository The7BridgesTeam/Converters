from io import StringIO

import pandas as pd
import pytest

from converters import NOS, Converter
from converters.contrib.dataframe import DataFrameToDictConverter
from ._test_utils import assert_deep_pattern_match


class ChildConverter(DataFrameToDictConverter):
    conversions = [
        'child_value',
    ]


@pytest.fixture
def converter_to_dict():
    class ConverterToDict(DataFrameToDictConverter):
        conversions = [
            'id',
            'parent_value',
            ('children', {'groupby': 'child_id', 'converter': ChildConverter}),
        ]

    Converter.register_converter_for_name(ConverterToDict, 'ConverterToDict')
    try:
        yield ConverterToDict
    finally:
        Converter.unregister_converter('ConverterToDict')


def test_dataframe_to_dict_converter(converter_to_dict):
    csv_data = """id,parent_value,child_id,child_value
    1,pval,1,cval
    1,pval,2,cval2
    1,pval,3,"""
    df = pd.read_csv(StringIO(csv_data))

    # Add a test that missing columns get defaulted
    converter_to_dict.conversions.append(('missing_column', NOS, 'missing column value'))

    converted = converter_to_dict.convert(df)
    assert_deep_pattern_match(
        converted,
        {
            'id': 1,
            'missing_column': 'missing column value',
            'parent_value': 'pval',
            'children': [
                {'child_value': 'cval',},
                {'child_value': 'cval2',},
                {'child_value': None,},
            ],
        },
    )


def test_errors_out_if_duplicate_values_with_no_groupby(converter_to_dict):
    # the parent_value is duplicated, which requires a 'groupby' key
    # (the same as a CSV dump from a DB query: we'll get multiple rows for one -> many
    # relations but the parent values should be consistent)
    csv_data = """id,parent_value,child_id,child_value
    1,pval,1,cval
    1,pval_error,2,cval2"""
    df = pd.read_csv(StringIO(csv_data))
    with pytest.raises(ValueError):
        converter_to_dict.convert(df)


def test_csv_multiple_columns(snapshot):
    class MyConverter(DataFrameToDictConverter):
        conversions = [
            ('cola', {'multiple_columns': True}),
            ('colb',),
        ]

    result = MyConverter.convert_csv(
        """\
cola,colb,cola,colb
a11,b11,a12,b12
a21,b21,a22,b22
"""
    )
    assert snapshot == result
    # and this is the main point, that cola declared as multiple_columns: True collects the entries
    # from each row into a list.
    assert result[0]['cola'] == ['a11', 'a12']
