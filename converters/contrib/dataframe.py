from io import StringIO, TextIOBase

import pandas as pd

from ..converter import Converter, create_compound_converter


def is_usable_as_dtype(arg):
    if arg is None:
        return False

    try:
        pd.api.types.pandas_dtype(arg)
        return True
    except TypeError:
        return False


def dataframe_getter(inst, attr, val, opts):
    groupby = opts.get('groupby')
    if groupby is not None:
        # when groupby is specified we always pass self through, so ignore attr
        if isinstance(groupby, dict):
            return inst.groupby(**groupby)
        return inst.groupby(groupby)

    if attr == 'self':
        return inst

    if attr not in inst:
        return None

    if opts.get('multiple_columns'):
        vals = inst.filter(regex=rf'{attr}(\.[0-9]+)?$')
        if opts.get('pass_through_series', False):
            return vals.iloc[0]
        return list(vals.iloc[0])

    vals = inst[attr]
    if opts.get('pass_through_series', False):
        return vals

    if vals.unique().shape[0] > 1:
        raise ValueError('Unable to determine value from column, multiple values exist')
    return vals.iloc[0]


class DataFrameToDictConverter(Converter):
    """Convert
    pandas dataframes to dictionaries.

    The easiest way to use it is with some CSV:

        >>> csv_str = 'col1,col2,col3\\n1, 2, 3\\n4,5,6\\n1, 3, 5'
        >>> class MyRowConverter(DataFrameToDictConverter):
        ...     conversions = [('col1', int), ('col3', int)]
        >>> MyRowConverter.convert_csv(csv_str)
        [{'col1': 1, 'col3': 3}, {'col1': 4, 'col3': 6}, {'col1': 1, 'col3': 5}]

    Note that you need to use converters and/or dtype options if you don't just want strings - data
    from CSV is assumed to be string data by default to avoid pandas automatic type detection which
    can produce inconsistent results.

    But cooler things can be achieved by nesting and using groupby:

        >>> csv_str = 'col1,col2,col3\\n1, 1, 1\\n1, 1, 2\\n1, 2, 1'
        >>> class MyGroupByCol2Converter(DataFrameToDictConverter):
        ...     conversions = [
        ...         ('col2', int),
        ...         ('col3', {
        ...             'groupby': {'level': 0},
        ...             'converter': lambda x: x['col3'].values[0],
        ...             'dtype': int,
        ...         }),
        ...     ]
        >>> class MyCSVConverter(DataFrameToDictConverter):
        ...     conversions = [
        ...         ('col1', int),
        ...         ('col2s', {
        ...             'groupby': 'col2', 'converter': MyGroupByCol2Converter,
        ...         }),
        ...     ]
        >>> MyCSVConverter.convert_csv(csv_str, groupby='col1')
        [{'col1': 1, 'col2s': [{'col2': 1, 'col3': [1, 2]}, {'col2': 2, 'col3': [1]}]}]

    Note that we used `'dtype': int` explicitly for `'col3'` because `DataFrameToDictConverter`
    would not be able to deduce a dtype automatically from the converter `MyGroupByCol2Converter`.

    ## Extra `conversions` options

    ### `'dtype'`

    Use this to cause us to specify what dtype we are expecting for the column. Before passing
    the dataframe through to the standard converter routines, we call `.astype(dtype=self.dtypes)`
    on it to ensure that dtypes specified here and any that can be deduced from the converters
    are what the column actually uses.

    ## `converter_options`

    ### `'extra_dtypes'`

    If you need to reference columns in the dataframe that are not listed in `conversions`,
    (for example in your converters) and they need to be something other than a string, then use
    this to specify their types.
    """

    from_class = pd.DataFrame
    to_class = dict

    converter_options = {
        # see notes in docstring
        'extra_dtypes': {},
    }

    # ----------------------------------------------------------------------------------------------
    # Convenience methods
    # ----------------------------------------------------------------------------------------------
    @classmethod
    def convert_csv(cls, csv, **kwargs):
        if isinstance(csv, str):
            csv_io = StringIO(csv)
        elif isinstance(csv, TextIOBase):
            csv_io = csv
        else:
            raise TypeError('Unknown CSV type')

        # pandas "helpfully" automatically detects data types in columns and so the type of a column
        # may vary depending on the data in the column. This is actually pretty unhelpful, as we
        # want to be sure of the types downstream. Therefore assume all are strings, and in
        # `instance_convert` we will apply dtypes dynamically.
        return cls.convert_dataframe_of_rows(pd.read_csv(csv_io, dtype=str), **kwargs)

    @classmethod
    def convert_dataframe_of_rows(cls, df, groupby=None) -> list:
        if isinstance(groupby, str):
            groupby = {'by': groupby}
        if groupby is None:
            groupby = {'level': 0}
        return [cls.convert(row[1]) for row in df.groupby(**groupby)]

    # ----------------------------------------------------------------------------------------------
    # Subclass methods
    # ----------------------------------------------------------------------------------------------
    def instance_convert(self):
        dtypes = self.dtypes
        if len(dtypes) > 0:
            self.source = self.source.astype(dtypes)

        return super().instance_convert()

    def dynamic_copy_attrs(self):
        attrs = list(self.normalize_copy_attrs(super().dynamic_copy_attrs()))
        for (t, s, opts) in filter(lambda x: x[2].get('groupby'), attrs):
            opts['converter'] = create_compound_converter(
                lambda gb_val_df_tuple: gb_val_df_tuple[1], opts['converter'],
            )
        return attrs

    @property
    def from_getter(self):
        return dataframe_getter

    def val_is_collection(self, val):
        return not isinstance(val, (pd.DataFrame, pd.Series)) and super().val_is_collection(val)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Replace nans with None
        self.source = self.source.where((pd.notnull(self.source)), None)

    # ----------------------------------------------------------------------------------------------
    # Internals
    # ----------------------------------------------------------------------------------------------
    @property
    def dtypes(self):
        if hasattr(self, '_dtypes_cache'):
            return self._dtypes_cache

        self._dtypes_cache = dict(self._resolved_converter_options['extra_dtypes'])
        # Deduce dtype info from the converters as much as possible, or use the explicitly
        # configured dtype setting in the converter copy attribute options
        self._dtypes_cache.update(
            {
                from_attr: dtype
                for from_attr, dtype in (
                    (from_attr, opts.get('dtype', opts.get('converter')))
                    for (to_attr, from_attr, opts) in self.dynamic_copy_attrs()
                )
                if from_attr in self.source and is_usable_as_dtype(dtype)
            }
        )
        return self._dtypes_cache
