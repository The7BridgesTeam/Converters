import logging
from collections import OrderedDict
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from importlib import import_module
from inspect import getfullargspec, signature
from numbers import Number
from threading import local

from pydash import clone_deep, get, pick

from ._utils import (
    class_or_instance_method,
    MergedClassProperty,
    cn,
    identity,
    infinite_counter,
    yield_forever,
    is_one_of_union_types,
    is_union_type,
)


__all__ = ['Converter', 'DictConverter', 'create_compound_converter', 'NOS']

log = logging.getLogger(__name__)
# Use in place of a from attribute to indicate this value is Not On the Source
# object and the default should be used.
NOS = '--Not On Source--'
_SENTRY = type('ConverterSentry', (), {})()
_COUNTER = infinite_counter()
DEDUPE_ALL = 'DEDUPE-ALL-FIELDS'


def _next_not_on_dest_attr():
    return '-not-on-dest-%d' % next(_COUNTER)


def _is_builtin_func(func):
    return func in [str, dict, list, int, float, bool]


class InvalidToClassException(TypeError):
    pass


class ValueRequired(ValueError):
    def __init__(self, value_name, msg=None):
        if msg is None:
            msg = f'{value_name!r} required but not found in the source'

        self.value_name = value_name
        super().__init__(msg)


class Converter:
    """Converter
    class to convert instances between types.

    ## Basics

    You create a subclass of `Converter` and configure it to convert from one
    instance to another. E.g:

        >>> class MyConverter(Converter):
        ...     from_class = dict
        ...     to_class = dict
        ...
        ...     conversions = [
        ...         'a',                            # to['a'] = from['a']
        ...         ('b', 'a'),                     # to['b'] = from['a']
        ...         ('c', NOS, 'a default'),        # to['c'] = 'a default'
        ...         ('d', 'a', lambda x: x * 2),    # to['d'] = from['a'] * 2
        ...         ('e', NOS, dict),               # to['e'] = dict()
        ...     ]

        >>> MyConverter({'a': 1}).convert()
        {'a': 1, 'b': 1, 'c': 'a default', 'd': 2, 'e': {}}

    You can also call `.convert()` directly on the model as a shorthand:

        >>> MyConverter.convert({'a': 1})
        {'a': 1, 'b': 1, 'c': 'a default', 'd': 2, 'e': {}}

    You can also use it to update an object rather than create a new one:

        >>> existing = {'a': 5, 'z': 'zzz'}
        >>> also_existing = MyConverter.convert({'a': 1}, dest=existing)  # update dest
        >>> existing
        {'a': 1, 'z': 'zzz', 'b': 1, 'c': 'a default', 'd': 2, 'e': {}}
        >>> also_existing is existing
        True

    You can use objects or dictionaries, as source or dest.

    - If dictionaries `dest[attr] = val` is used to set, `dest[attr]` to get.
    - If objects `setattr(dest, attr, val)` is set, and `getattr(dest, attr)` is get.
        (Thanks to `pydash.get`!)

    So for an object:

        >>> AClass = type('AClass', (), {})
        >>> class AnObjectConverter(Converter):
        ...     from_class = AClass
        ...     to_class = AClass
        ...     conversions = [
        ...         ('a', lambda a: a * 2)          # to.a = from_.a
        ...     ]
        >>> an_inst = AClass()
        >>> an_inst.a = 5
        >>> AnObjectConverter.convert(an_inst).a
        10

    It's also possible to use Union for specifying `from_class`. E.g:

        >>> from typing import Union
        >>> class MyObject(object):
        ...     def __init__(self, a):
        ...         self.a = a
        ...
        >>> class MyConverter(Converter):
        ...     from_class = Union[dict, object]
        ...     to_class = dict
        ...
        ...     conversions = ['a']
        ...
        >>> MyConverter.convert({'a': 10})['a']
        10
        >>> MyConverter.convert(MyObject(a=10))['a']
        10

    Using Union on `to_class` is forbidden, as it would be not possible to choose a destination
    type.

    ### `conversions`

    The `conversions` provide flexibility of what to copy, to where
    and how to do so. The following forms are equivalent:

        conversions = [
            'a',
            ('a',),
            ('a', lambda x: x),
            ('a', {}),
            ('a', 'a'),
            ('a', 'a', {}),
        ]

    The first argument is the attribute on the target.

    The second depends on its type:

    - <strong>`str`</strong>: the attribute on the source object to copy <br/>
    - <strong>`NOS`</strong>: indicates "Not On Source", which means this won't be copied
        from the source but can be generated using a default.

    Otherwise the second is treated as though it were the third attribute, and
    the second attribute were the same as the first attribute.

    The third depends on its type *and* the type of the second. When
    the second is a string (or there is no second):

    - <strong>`string`</strong>: method name to use as converter
    - <strong>`Callable`</strong>: function converter to convert this attribute
    - <strong>`Converter` subclass</strong>: converter to use to convert this attribute
    - <strong>`dict`</strong>: options (see below).

    ## Context

    Converter also has a context you can use to pass information through to nested converters.
    Simply specify the value you are passing to the `context` key-word attribute:

        >>> class MySubConverter(DictConverter):
        ...     conversions = [
        ...         'from_context',
        ...     ]
        >>> class MyConverter(DictConverter):
        ...     conversions = [
        ...         'from_context',
        ...         ('subs', MySubConverter),
        ...     ]
        >>> MyConverter.convert({
        ...     'from_context': 'OVERRIDE',
        ...     'subs': [{}],
        ... }, context={'from_context': 'context'})
        {'from_context': 'OVERRIDE', 'subs': [{'from_context': 'context'}]}

    Note that

    - any values in the source take precedence over those in the context. Converter methods
      can look at the current context by looking in `self.context`, but note that this will only
      be populated while the converter is running.
    - the context is global, so if you call other converters manually from your converter then they
      will see the same context. If you pass `context={}` to them then that context will be
      merged into the existing context for the duration of the child converter execution.

    ## List of converter class options

        converter_options = {
            <OPTIONS>
        }

    These options configure the behaviour of the whole converter. Subclasses
    may add further options. Defaults are shown in the list:

    - <strong>`"convert_nones_to_blanks": Bool [False]`</strong> <br/>
        Convert source `None` values to blank strings
    - <strong>`"include_nones": Bool [True]`</strong> <br/>
        Copy source `None`s onto the destination, otherwise drop them
    - <strong>`"include_empty_strings": Bool [True]`</strong> <br/>
        Copy source `""`s onto the destination, otherwise drop them
    - <strong>`"pass_attrs_to_init": Bool [False]`</strong> <br/>
        Pass all attributes to be copied as key-word args
        to the `to_class` constructor
    - <strong>`"merge_all": Bool [False]`</strong> <br/> 
        Merge all attributes, see `"merge"` converter copy attribute.
    - <strong>`"copy_only": Bool [False]`</strong> <br/> 
        Only allow copying attributes. Expects dest parameter to be specified,
        as it prevents creating a new destination instance.

    ## List of converter copy attribute options

        conversions = [
            ('attr', {<OPTIONS>}),
        ]

    The converter copy attribute options may be specified for each attribute that
    you want to copy, and affect how that is done. Subclasses may add further options.

    This is a list of the available options, more details on the complex ones
    are given later. The `types` that can be passed are specified in the list and
    the default where appropriate.

    - <strong>`"converter": str|Callable|Converter`</strong><br/>
        The converter to use to convert this attribute. If a `str`, then it is a method
        name to use as a converter.
    - <strong>`"converter_wants_nones": Bool [False]`</strong> <br/>
        Pass the converter `None`s instead of using
        `None` directly and not hitting the converter.
    - <strong>`"default": None|str|Number|Callable`</strong> <br/>
        A default to use if the source is
        not provided. If a `Callable` the result of calling the callable is used.<br/>
        Can be one of two forms:

            def filter_out_evens(source_value):
                # this is passed just the source value so logic must depend only on that:
                return source_value % 2 == 0

            def filter_out_based_on_another_attribute(source_value, source):
                # can access the whole source object as well:
                return source['another_attribute'] % 2 == 0 and source_value % 3 == 0

    - <strong>`"filter": Callable` </strong><br/>
        Either filter out items in a collection, or if the source attribute is a singular value,
        then this determines whether we include it on the output or not.
    - <strong>`"map": Bool [True]`</strong> <br/>
        If `True`, map items in a collection with the converter. <br/>
        if `False`, pass the collection straight to the converter.
    - <strong>`"max_len": Integer`</strong> <br/>
        Truncate the attribute being copied to this length
    - <strong>`"merge": Bool [False]`</strong><br/>
        Merge this property into the destination attribute
        instead of overwriting it.
    - <strong>`"pluralize": Bool [False]`</strong><br/>
        If the source attribute is not a collection type
        (e.g. list or other iterable that is not a string or a dict), then wrap it
        in a list, so that the destination will always be a collection.
    - <strong>`"reverse_attr_name": str`</strong><br/>
    - <strong>`"required": Bool|Callable [False]`</strong>
        If `True` and the field is not present in the source, an exception will be raised
        when trying to convert the source.

        If a callable is passed, it will be ran after that with the value from the source
        as a single argument. If the return value is `False`, the convert will again fail.

        NOTE: the callable will be called with the "raw" value from the source, i.e. before
        any other convert options (such as `convert_nones_to_blanks`) are applied.
    - <strong>`"sort": Bool|Callable [False]`</strong> <br/>
        If set, the items in a collection will be sorted in accordance to
        the sorting method (`True` will compare them directly)

    ## Washers

        converter_washers = {
            Number: lambda n: round(n, 2),  # example: round all numbers to 2dp.
            ...
        }

    You can add "washers" to the converter class as well to "wash" the values
    before setting them on their destination according to their type. This
    could be achieved by using converters, but then you'd need to apply the same
    conversions to each attribute of that type, which would be tedious.

    ## Example configuration

    Here's an example with a few ways of configuring the Converter:

        >>> class MyConverter(Converter):
        ...     # could have used DictConverter since we're just going to and from dicts.
        ...     from_class = dict
        ...     to_class = type('AdHocClass', (), {})
        ...
        ...     conversions = [
        ...         'attr1',
        ...         ('attr1_alternative',),
        ...         ('renamed_attr', 'attr2'),
        ...
        ...         # You can pass a subconverter in the options dictionary (which
        ...         # can be the second or third argument depending on if the source
        ...         # and destination fields have the same names or not):
        ...         ('greeting', {'converter': lambda x: 'Very many %ss!' % x}),
        ...
        ...         # If it's the only option, you can pass the Converter (function
        ...         # or class) as the second argument directly.
        ...         ('multiply_this', lambda x: x * 2),
        ...         # similarly as the third argument.
        ...         ('add_this_dest', 'add_this_from', lambda x: x + 2),
        ...
        ...         # You can also indicate that the attribute is Not On the Source object,
        ...         # implying it should be added:
        ...         ('added_attr', NOS, {'default': 'added attr value'}),
        ...         # and because that's a common pattern, if you're just using the
        ...         # default option you can pass that as the third argument directly
        ...         # when using NOS:
        ...         ('added_attr_2', NOS, 'added attr value 2'),
        ...     ]

        >>> res = MyConverter({
        ...     'attr1': 'attr1 value',
        ...     'attr1_alternative': 'attr1 alternative value',
        ...     'attr2': 'attr2 value',
        ...     'greeting': 'hello',
        ...     'multiply_this': 3,
        ...     'add_this_from': 5,
        ... }).convert()
        >>> res.attr1
        'attr1 value'
        >>> res.attr1_alternative
        'attr1 alternative value'
        >>> res.renamed_attr
        'attr2 value'
        >>> res.greeting
        'Very many hellos!'
        >>> res.multiply_this
        6
        >>> res.add_this_dest
        7
        >>> res.added_attr
        'added attr value'
        >>> res.added_attr_2
        'added attr value 2'

    ## Converter copy attribute options details

    ### `default`

    Use this value (or the result of executing this function) when the source
    does not have the source attribute. See above for examples.

    ### `reverse_attr_name`

    Instead of setting the value on the new object, the new object is set on
    the value using this attribute name. So:

        >>> class MyConverter(Converter):
        ...     from_class = type('AdHocClass', (), {})
        ...     to_class = from_class
        ...
        ...     conversions = [
        ...         ('obj_attr', {'reverse_attr_name': 'reverse_attr'}),
        ...     ]
        >>> aa = MyConverter.from_class()
        >>> aa.obj_attr = MyConverter.from_class()
        >>> bb = MyConverter(aa).convert()
        >>> bb.obj_attr == aa.obj_attr
        True
        >>> bb.obj_attr.reverse_attr == bb
        True

    This is useful e.g. when building django model graphs where you have a reverse
    foreign key manager that you can't assign to until the object is saved.

    ### `filter`

    The values in the iterable source attribute are filtered by this function.
    It returns True to include a value and False not to.

        >>> class FilteredConverter(DictConverter):
        ...     conversions = [
        ...         ('bigger_than_ten', 'numbers', {'filter': lambda p: p > 10}),
        ...     ]

        >>> FilteredConverter({'numbers': [3, 11]}).convert()['bigger_than_ten']
        [11]

    ### `map`

    How to handle collections (e.g. lists, but not dicts).

    When `True`, the default, the converter is used as a mapper on the source
    collection. When `False`, the converter is applied directly to the source
    collection.

        >>> class MapExampleConverter(DictConverter):
        ...     conversions = [
        ...         ('mapped', lambda col: col * 2),
        ...         ('unmapped', {'converter': lambda col: col * 2, 'map': False})
        ...     ]

        >>> MapExampleConverter({
        ...     'mapped': [3, 11],
        ...     'unmapped': [3, 11],
        ... }).convert()
        {'mapped': [6, 22], 'unmapped': [3, 11, 3, 11]}

    ### `max_len`

    Uses the first `max_len` items without any warnings. The default implementation
    simply slices the source value. If it isn't sliceable you'll get a crash.

    Subclasses can override
    `truncate_value(self, value, max_len)` to implement this in different ways
    (e.g. they may need to take account of escaped characters)

        >>> class TruncatedConverter(DictConverter):
        ...     conversions = [
        ...         ('truncated_string', 'string', {'max_len': 10}),
        ...         ('truncated_list', 'list', {'max_len': 2}),
        ...     ]
        >>> res = TruncatedConverter.convert({'string': 'Hello world!', 'list': [1, 2, 3]})
        >>> res['truncated_string']
        'Hello worl'
        >>> res['truncated_list']
        [1, 2]

    ### `pluralize`

    Normalizes a source attribute into a collection, so that the converter can
    rely on being able to map correctly.

    An example where you might use this is if an API returns a field `'packages'`,
    which is either a list of dictionaries, or a single dictionary if there is just
    one package. To handle it most easily, use `'pluralize'` to initially normalize
    the single package to a list of packages with just one entry, and then the
    subsequent converter logic will work consistently.

        >>> class PluralizingConverter(DictConverter):
        ...     conversions = [
        ...         ('pluralize_me', {'pluralize': True}),
        ...         ('and_me', {'pluralize': True}),
        ...     ]
        >>> PluralizingConverter.convert({
        ...     'pluralize_me': {'some': 'dict'},
        ...     'and_me': ['a', 'b'],
        ... })
        {'pluralize_me': [{'some': 'dict'}], 'and_me': ['a', 'b']}

    ### `sort`

    Only applicable to collections (e.g. lists but not dicts).

    If set, when all the previous conversions are done, the results will be sorted
    in accordance to the sorting method provided. The sorting method is the same as
    the `key` argument of the `sorted` built-in function. If the sorting method is
    set to `True`, the elements will be compared directly.

        >>> from operator import itemgetter

        >>> class SortExampleConverter(DictConverter):
        ...     conversions = [
        ...         ('nums', {'sort': True}),
        ...         ('dicts', {'sort': itemgetter('name')})
        ...     ]

        >>> SortExampleConverter({
        ...     'nums': [4, 2, 1, 3],
        ...     'dicts': [
        ...         {
        ...             'name': 'Bob',
        ...             'age': 22,
        ...         },
        ...         {
        ...             'name': 'Alice',
        ...             'age': 33,
        ...         },
        ...     ]
        ... }).convert()
        {'nums': [1, 2, 3, 4], 'dicts': [{'name': 'Alice', 'age': 33}, {'name': 'Bob', 'age': 22}]}

    ## Whole converter `converter_options`

    There are some options that you can apply for the whole of the converter,
    which you can do using the `converter_options` class attribute. These
    can be overridden by subclasses.

    ### `"convert_nones_to_blanks"`, `"include_nones"` and `"include_empty_strings"`

        >>> class MyConverter(Converter):
        ...     from_class = dict
        ...     to_class = dict
        ...
        ...     converter_options = {
        ...         'convert_nones_to_blanks': True,
        ...         'include_nones': False,
        ...     }
        ...     conversions = [('to_attr', 'from_attr')]

    Empty dictionary because `"include_nones"` is not set:

        >>> MyConverter({'from_attr': None}).convert()
        {}

    `"include_nones"` now set, and `"convert_nones_to_blanks"` inherited from `MyConverter`:

        >>> class MySubclass1Converter(MyConverter):
        ...     converter_options = {
        ...         'include_nones': True,
        ...     }
        >>> MySubclass1Converter({'from_attr': None}).convert()
        {'to_attr': ''}

    `"include_empty_strings"` now set, and `"convert_nones_to_blanks"` inherited from `MyConverter`:

        >>> class MySubclass1Converter(MyConverter):
        ...     conversions = [
        ...         ('to_attr', 'from_attr'),
        ...         ('to_attr_none', 'from_attr_none'),
        ...         ('to_attr_valued', 'from_attr_valued'),
        ...     ]
        ...     converter_options = {
        ...         'include_nones': True,
        ...         'include_empty_strings': False,
        ...     }
        >>> MySubclass1Converter(
        ...     {'from_attr': '', 'from_attr_none': None, 'from_attr_valued': 'val'}
        ... ).convert()
        {'to_attr_valued': 'val'}

    `"convert_nones_to_blanks"` now disabled:

        >>> class MySubclass2Converter(MySubclass1Converter):
        ...     converter_options = {
        ...         'convert_nones_to_blanks': False,
        ...     }
        >>> MySubclass2Converter({'from_attr': None}).convert()
        {'to_attr': None}

    ### `converter_washers`

    Provides a convenient way of doing transforms on results of particular types.
    This happens after any previous convert step and before any truncation.

    For example:

        >>> from decimal import Decimal
        >>> from numbers import Number
        >>> from unidecode import unidecode
        >>> class MyStrWasher(DictConverter):
        ...     conversions = [
        ...         ('attr1', {'max_len': 17}),
        ...         'num_attr',
        ...     ]
        ...     converter_washers = {
        ...         Number: lambda n: round(n, 2),
        ...         str: unidecode,
        ...     }
        >>> res = MyStrWasher.convert({
        ...     'attr1': 'ßömé wei®∂ çTring',
        ...     'num_attr': Decimal('3.1415'),
        ... })
        >>> res['attr1'] == unidecode('ßömé wei®∂ çTring')[:17]
        True
        >>> res['num_attr']
        Decimal('3.14')
    """

    # -------------------------------------------------------------------------
    # Class config
    # -------------------------------------------------------------------------
    # Map of shape: { 'converter_name_such_as_datetime': ConverterSubclass }
    named_converters = {}
    converter_options = {
        'convert_nones_to_blanks': False,
        'include_nones': True,
        'include_empty_strings': True,
        'pass_attrs_to_init': False,
        'merge_all': False,
        'copy_only': False,
    }

    # -------------------------------------------------------------------------
    # Class methods
    # -------------------------------------------------------------------------
    @classmethod
    def register_converter_for_name(cls, converter, name):
        if not isinstance(converter, type):
            converter_func = converter
            converter = type(
                '%sAdHocConverter' % converter.__name__,
                (Converter,),
                {
                    'convert': lambda self: converter_func(self.source),
                    'from_class': object,
                    'to_class': object,
                },
            )
        cls.named_converters[name] = converter

    @classmethod
    def unregister_converter(cls, name):
        del cls.named_converters[name]

    def dynamic_copy_attrs(self):
        """Returns list of form [(to_attr_name, from_attr_name, opts)]"""
        converter_attrs = clone_deep(getattr(self, 'conversions', []))

        # TODO: Deprecate in favour of using defaults
        additional_attrs = [
            (k, NOS, {'default': v})
            for k, v in getattr(self, 'converter_additional_attrs', {}).items()
        ]

        # normalize here so we can access opts reliably
        normalized_converter_attrs = self.normalize_copy_attrs(converter_attrs)
        for k, v in self.extra_attrs.items():
            try:
                ca_dest, ca_source_key, ca_opts = next(
                    a for a in normalized_converter_attrs if a[0] == k
                )
                ca_opts['_kwarg_override'] = v
            except StopIteration:
                # extra attr not found in existing attributes, so add it
                normalized_converter_attrs.append((k, NOS, {'_kwarg_override': v}))

        return [*normalized_converter_attrs, *additional_attrs]

    # -------------------------------------------------------------------------
    # Instance methods
    # -------------------------------------------------------------------------
    def __init__(self, source, *, context=None, dest=None, _extra=None, **extra_attrs):
        _extra = _extra or {}
        if getattr(self, 'from_class', None) is None:
            raise TypeError('%s has no from_class' % (cn(self),))
        if getattr(self, 'to_class', None) is None:
            raise TypeError('%s has no to_class' % (cn(self),))
        if is_union_type(getattr(self, 'to_class', None)):
            raise InvalidToClassException('Specifying to_class as Union type is forbidden.')

        if source is not None and not self._is_valid_source_type(source):
            raise TypeError(
                '%s source is not an instance of %s: %r'
                % (cn(self), self.from_class.__name__, source)
            )
        self.dest = dest
        self.source = source
        self.extra_attrs = extra_attrs
        # subclasses may wish to modify this in `instantiate` if they want to
        # do a "find and modify or create" style conversion.
        self.creating = dest is None
        # Used for if we want to pass any other vars to this converter to be used in the child
        self._extra = _extra
        self._context = context
        self._normalized_attrs = self._normalized_dynamic_copy_attrs()

    @property
    def context(self):
        # There is only one context for all converters, as generally converter stacks are all
        # related so you won't get random things in the context from unrelated converters. Obviously
        # we could change this in the future to hide contexts from each other if there was a
        # compelling use case.
        return getattr(Converter._converter_context_local, 'context', {})

    @context.setter
    def context(self, value):
        Converter._converter_context_local.context = value

    def default_getter(self, src, attr, default, *args, **kwargs):
        if attr == 'self':
            return self.source
        return get(src, attr, default)

    def default_setter(self, inst, to_attr, val, *args, **kwargs):
        return setattr(inst, to_attr, val)

    @property
    def setter(self):
        return self.default_setter

    @property
    def from_getter(self):
        return self.default_getter

    @property
    def to_getter(self):
        return self.default_getter

    def params_for_initialization(self):
        dct = OrderedDict()
        for to_attr, from_attr, opts in self._normalized_attrs:
            if not self._is_initialization_attr(to_attr, opts):
                continue
            val = self._normalize_value(to_attr, from_attr, opts)
            if val is _SENTRY:
                continue
            dct[to_attr] = (val, opts)
        return dct

    def params_for_population(self, inst):
        dct = OrderedDict()
        for to_attr, from_attr, opts in self._normalized_attrs:
            if self._is_initialization_attr(to_attr, opts):
                continue
            val = self._normalize_value(to_attr, from_attr, opts, inst)
            if val is _SENTRY:
                continue
            dct[to_attr] = (val, opts)
        return dct

    @class_or_instance_method
    def convert(self, *args, **kwargs):
        # You should not override this. If you want to hijack raw convert
        # (e.g. perhaps to take a shortcut based on the source) then override
        # `instance_convert` below.

        # this supports being called as a class method...
        if isinstance(self, type):
            cls = self
            return cls(*args, **kwargs).convert()

        with self._updated_context():
            return self.instance_convert()

    def instance_convert(self):
        # Override this if you want to control conversion at the top level.
        #
        # In general it is expected that you will call through to this if you
        # need to do the full conversion, and only return something else if you have
        # a specific shortcut you'd like to do.
        init_attrs = self.params_for_initialization()
        if self.dest is not None:
            inst = self.populate_instance(self.dest, init_attrs)
        else:
            inst = self.instantiate(init_attrs)
            if inst is None or inst is _SENTRY:
                return inst
        self.inst = inst
        pop_parms = self.params_for_population(inst)
        self.populate_instance(inst, pop_parms)
        post_convert = getattr(self, 'post_convert', None)
        if post_convert is not None:
            inst = post_convert(inst)
        return inst

    def instantiate(self, dct):
        if self._resolved_converter_options['copy_only']:
            raise TypeError('Cannot instantiate new instance. copy_only parameter set to true')

        attr_val_only_map = {attr: val_and_opts[0] for attr, val_and_opts in dct.items()}
        return self.to_class(**attr_val_only_map)

    def populate_instance(self, inst, params):
        for to_attr, (val, opts) in params.items():
            if opts.get('merge', False):
                # if we've been explicitly told to merge, don't attempt the set
                # as it should be pointless and it may break, say if we're merging
                # into a readonly list.
                continue
            self._set_value(inst, to_attr, opts, val)
        return inst

    def val_is_collection(self, val):
        return isinstance(val, Iterable) and not isinstance(val, str) and not isinstance(val, dict)

    def pluralize_val(self, val):
        return [val]

    def wash_result(self, val):
        for washer_type, washer in self._resolved_converter_washers.items():
            if not isinstance(val, washer_type):
                continue

            return washer(val)

        return val

    def truncate_value(self, value, max_len, opts):
        return value[:max_len]

    # -------------------------------------------------------------------------
    # Private methods
    # -------------------------------------------------------------------------
    _converter_context_local = local()
    _resolved_converter_options = MergedClassProperty('converter_options')
    _resolved_converter_washers = MergedClassProperty('converter_washers')

    def _is_valid_source_type(self, source):
        if is_union_type(self.from_class):
            return is_one_of_union_types(source, self.from_class)
        else:
            return isinstance(source, self.from_class)

    def _filter_includes_val(self, filter_, val):
        if _is_builtin_func(filter_):
            return filter_(val)

        fsig = signature(filter_)
        if len(fsig.parameters) == 1:
            return filter_(val)

        # otherwise pass both; this will crash if the filter has an unsupported signature
        return filter_(val, self.source)

    def _convert_child(self, to_attr, opts, val, inst):
        filter_ = opts.get('filter', _SENTRY)
        sub_converter = opts.get('converter', _SENTRY)
        reverse_attr_name = opts.get('reverse_attr_name')

        should_map = opts.get('map', True) and self.val_is_collection(val)
        if not should_map and filter_ is not _SENTRY:
            # we may be able to filter this out
            if not self._filter_includes_val(filter_, val):
                return _SENTRY

        if sub_converter is _SENTRY:
            if filter_ is _SENTRY:
                if reverse_attr_name and inst is not _SENTRY:
                    self._set_value(val, reverse_attr_name, {}, inst)
                return val

            # filter_ is set, that means we need to fall through as it's
            # implemented later.
            sub_converter = identity

        sub_converter_wants_nones = opts.get('converter_wants_nones', False)
        if val is None and not sub_converter_wants_nones:
            return None

        if isinstance(sub_converter, str):
            sub_converter_str = sub_converter
            sub_converter = getattr(self, sub_converter_str, None)
            if not isinstance(sub_converter, Callable):
                sub_converter = self.named_converters[sub_converter_str]

        if isinstance(sub_converter, type) and issubclass(sub_converter, Converter):

            def cfunc(to_convert, dest=None, **kwargs):
                # TODO DEV: Test passing _extra to sub converters
                return sub_converter(to_convert, dest=dest, _extra=self._extra, **kwargs).convert()

        elif isinstance(sub_converter, Callable):
            cfunc = sub_converter
        else:
            raise TypeError(
                'Unexpected type %s of subconverter %s for to attribute %s'
                % (cn(sub_converter), sub_converter, to_attr)
            )

        kwargs = {}
        if reverse_attr_name:
            if inst is _SENTRY:
                raise ValueError(
                    "'reverse_attr_name' set on an initialization property, use "
                    "{'initialization_attribute': False} in the options to fix this"
                )
            kwargs[reverse_attr_name] = inst

        # these built-in functions may be used as converters, but they don't have
        # signature information
        if _is_builtin_func(cfunc):
            wants_dest = False
            wants_inst = False
        else:
            cfunc_parms = signature(cfunc).parameters
            wants_dest = 'dest' in cfunc_parms
            # some functions use inst as the name for the value, so they don't
            # want inst passed as a separate kwarg
            wants_inst = 'inst' in cfunc_parms and list(cfunc_parms).index('inst') != 0

        sub_dest = (
            self.to_getter(inst, to_attr, _SENTRY) if self._attr_should_be_merged(opts) else _SENTRY
        )
        if should_map:
            # normalize to list
            val = [
                subval
                for subval in (
                    cfunc(val_, **kwargs, **({'dest': sd} if sd is not _SENTRY else {}))
                    for val_, sd in zip(
                        val,
                        sub_dest
                        if wants_dest and sub_dest is not _SENTRY
                        else yield_forever(_SENTRY),
                    )
                    if filter_ is _SENTRY or self._filter_includes_val(filter_, val_)
                )
                if subval is not _SENTRY
            ]
        else:
            if wants_dest and sub_dest is not _SENTRY:
                kwargs['dest'] = sub_dest
            if wants_inst:
                kwargs['inst'] = inst
            val = cfunc(val, **kwargs)

        return val

    def _is_initialization_attr(self, attr, opts):
        """Judge whether this attribute should be passed as an init kwarg or
        set on the destination after the init.

        By default attributes are set after init, but the options
        'initialization_attribute' and 'reverse_attr_name', as well as the Converter
        subclass `converter_options` option `pass_attrs_to_init` can be used to
        modify this as follows:

        If 'initialization_attribute' is set in the attribute options, then it
        is obeyed.

        Else, if `converter_options.pass_attrs_to_init` is set on the Converter,
        the attribute is passed to init...

        ...UNLESS reverse_attr_name is set, because this implies the parent must
        be instantiated first in order that it can be passed as an attribute to
        the child.
        """
        attr_is_deep = '.' in attr
        attrs_generally_are_for_init = self._resolved_converter_options['pass_attrs_to_init']
        attr_has_a_reverse_attribute = bool(opts.get('reverse_attr_name'))
        attr_converter_wants_instance = bool(opts.get('pass_instance_to_converter'))
        attr_is_merging = opts.get('merge', False)
        is_initialization_attr = opts.get(
            'initialization_attribute',
            attrs_generally_are_for_init
            and not attr_converter_wants_instance
            and not attr_is_deep
            and not attr_has_a_reverse_attribute
            and not attr_is_merging,
        )
        return is_initialization_attr

    def _attr_should_be_merged(self, opts):
        return opts.get('merge', self._resolved_converter_options['merge_all'])

    def _normalized_dynamic_copy_attrs(self):
        """Generates (to_attr_name, from_attr_name, opts) tuples from
        the class's `conversions` list.
        """
        return list(self.normalize_copy_attrs(self.dynamic_copy_attrs()))

    @classmethod
    def normalize_copy_attrs(cls, copy_attrs):
        """Normalizes the copy_attrs to `(to_attr_name, from_attr_name, opts)` tuples."""
        normalized_copy_attrs = []
        for to_attr, from_attr, opts in (
            cls.normalize_single_copy_attr(field) for field in copy_attrs
        ):
            # Do some sanity checking
            default = opts.get('default', _SENTRY)
            if default is not _SENTRY and not (
                isinstance(default, Callable)
                or isinstance(default, Number)
                or isinstance(default, str)
            ):
                raise TypeError(
                    'default option in converter can only be a callable, number or str. '
                    'Default for (%s, %s) on %s has type "%s"'
                    % (to_attr, from_attr, cls.__name__, cn(default))
                )
            normalized_copy_attrs.append((to_attr, from_attr, opts))
        return normalized_copy_attrs

    @classmethod
    def normalize_single_copy_attr(cls, field):
        if isinstance(field, str):
            # of form 'to_and_from_field'
            return (field, field, {})

        if isinstance(field, Callable):
            # this supports subclasses that result in non-map objects (e.g. strings,
            # lists etc. as opposed to dictionaries / instances) and where you want
            # to provide a converter that just acts on the source.
            #
            # As there may be multiple unnamed copy attributes we need to give them
            # unique to values so they do not conflict in the internal intermediate
            # dictionary representation.
            return (_next_not_on_dest_attr(), 'self', {'converter': field})

        if isinstance(field, Iterable):

            if len(field) == 1:
                # of form ('to_and_from_field',)
                return (field[0], field[0], {})

            if len(field) == 2:
                if field[1] is NOS:
                    # use default_if_nos from class
                    nos_default = getattr(cls, 'default_if_nos', None)
                    if nos_default is not None:
                        return (field[0], NOS, {'default': nos_default})

                    return (field[0], NOS, {})

                if isinstance(field[1], str):
                    # of form ('to_field', 'from_field')
                    return (field[0], field[1], {})

                if isinstance(field[1], Callable):
                    # of form ('to_and_from_field', Converter)
                    return (field[0], field[0], {'converter': field[1]})

                # otherwise of form ('to_and_from_field', {'options': blah})
                return (field[0], field[0], field[1])

            if len(field) == 3:
                # of form
                # ('to_field' | None, 'from_field' | NOS, Converter | default | {'options': blah})
                field_0 = field[0] or _next_not_on_dest_attr()
                if not isinstance(field_0, str):
                    raise TypeError(
                        '%s copy converter attribute "to" field %r is invalid' % (cn(cls), field_0)
                    )

                field_1 = field[1]
                if field_1 is not NOS and not isinstance(field_1, str):
                    raise TypeError(
                        '%s copy converter attribute "from" field %r is invalid'
                        % (cn(cls), field_1)
                    )

                field_2 = field[2]

                if isinstance(field_2, dict):
                    # ('to_field', 'from_field', {opts})
                    return (field_0, field_1, field_2)

                if field_1 is NOS:
                    # ('to_field', NOS, <default>)
                    return (field_0, field_1, {'default': field_2})

                if (
                    not isinstance(field_2, Callable)
                    and not isinstance(field_2, str)
                    and not isinstance(field_2, Converter)
                ):
                    raise TypeError(
                        '%s copy converter to field %s converter %r is invalid'
                        % (cn(cls), field_0, field_2)
                    )

                # ('to_field', 'from_field', Converter)
                return (field_0, field_1, {'converter': field_2})

        raise TypeError(f'Copy field spec is not valid: {field!r}')

    def _normalize_value(self, to_attr, from_attr, opts, inst=_SENTRY):
        val = self._get_value(inst, from_attr, opts)
        value_requirement = opts.get('required', False)

        if val is _SENTRY:
            if value_requirement:
                raise ValueRequired(from_attr)

            return _SENTRY

        if callable(value_requirement) and not value_requirement(val):
            raise ValueRequired(
                from_attr, f'{from_attr!r} value from source does not satisfy requirement condition'
            )

        val = self._convert_child(to_attr, opts, val, inst)

        if not self._resolved_converter_options['include_nones'] and val is None:
            return _SENTRY

        if val is None and self._resolved_converter_options['convert_nones_to_blanks']:
            val = ''

        if not self._resolved_converter_options['include_empty_strings'] and val == '':
            return _SENTRY

        if val is _SENTRY:
            return _SENTRY

        if not opts.get('skip_wash', False):
            val = self.wash_result(val)

        max_len = opts.get('max_len')
        if max_len is not None:
            val = self.truncate_value(val, max_len, opts)

        sort_ = opts.get('sort', False)
        if sort_:
            if not self.val_is_collection(val):
                raise ValueError('sort is only applicable to collections')

            if callable(sort_):
                sort_key = sort_
            elif sort_ is True:
                sort_key = lambda x: x  # NOQA: E731
            else:
                raise TypeError('sort value must be a boolean or a callable')

            val = sorted(val, key=sort_key)

        return val

    def _get_value(self, inst, from_attr, opts):
        if opts.get('_kwarg_override') is not None:
            return opts['_kwarg_override']
        if opts.get('pass_instance_to_converter', False):
            val = inst
        elif from_attr == NOS:
            val = _SENTRY
        elif opts.get('getter', _SENTRY) is not _SENTRY:
            val = opts['getter'](self.source, from_attr, opts)
        else:
            val = self.from_getter(self.source, from_attr, _SENTRY, opts)

        if val is _SENTRY:
            # try the context
            val = get(self.context, from_attr, _SENTRY)

        if val is _SENTRY or val is None or (isinstance(val, str) and val == ''):
            default = opts.get('default', _SENTRY)
            if default is _SENTRY and val is _SENTRY:
                # no default and no val, nothing to do
                return _SENTRY

            if default is not _SENTRY:
                # use the default
                if isinstance(default, Callable):
                    return default()
                return default

            # val is None or an empty string but no default so fall through.

        if opts.get('pluralize', False) and not self.val_is_collection(val):
            val = self.pluralize_val(val)
        return val

    def _set_value(self, inst, to_attr, opts, val):
        left, _, right = to_attr.partition('.')
        if right:
            # set on a deep path, attempt to recurse.
            subval = self.to_getter(inst, left, None, opts, right=right)
            if subval is None:
                return
            self._set_value(subval, right, opts, val)
            return

        # Optimization: The below section is an optimization for the common cases to avoid the
        # expensive `pick` and `getfullargspec` calls on the golden path.
        setter = get(opts, 'setter')
        if not setter:
            # no custom setter, do the normal thing
            if isinstance(inst, dict):
                inst[to_attr] = val
                return

            if not isinstance(inst, Iterable):
                self.setter(inst, to_attr, val, opts)
                return

            # otherwise we can't do something quick, so fallthrough to normal processing
        # End of optimization

        if setter:
            if isinstance(setter, str):
                setter = getattr(self, setter)
            # otherwise we assume it's a callable
        else:
            if isinstance(inst, dict):

                def setter(inst, to_attr, val):
                    inst[to_attr] = val

            else:

                def setter(inst, to_attr, val, opts):
                    self.setter(inst, to_attr, val, opts)

        for inst_ in (
            inst
            if not isinstance(inst, dict) and isinstance(inst, Iterable) and not get(inst, 'set')
            else [inst]
        ):
            setter(
                **pick({**locals(), 'inst': inst_, 'attr': to_attr}, getfullargspec(setter).args)
            )

    @contextmanager
    def _updated_context(self):
        new_built_context = {} if not hasattr(self, 'build_context') else self.build_context()
        new_context = self._context or {}

        old_context = self.context or {}
        self.context = {**old_context, **new_built_context, **new_context}
        try:
            yield
        finally:
            self.context = old_context


class DictConverter(Converter):
    """Convenience superclass converter for converting plain old dicts."""

    from_class = dict
    to_class = dict


Converter.register_converter_for_name(DictConverter, 'dict')


def create_compound_converter(*converters):
    def compound_converter(val, **kwargs):
        result = val
        for conv in converters:
            # currently this only supports class and function converters, simply because
            # that's what I need right now.
            if isinstance(conv, type) and issubclass(conv, Converter):
                result = conv(result, **kwargs).convert()
            else:
                result = conv(result, **kwargs)
        return result

    return compound_converter
