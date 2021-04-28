import sys
from datetime import datetime, timedelta, timezone
from operator import itemgetter
from typing import Union
from unittest import mock

import pytest

from converters import NOS, Converter, DictConverter, InvalidToClassException, ValueRequired
from ._test_utils import assert_deep_pattern_match, nullcontext


def test_converter_invalid_field_spec():
    class MyConverter(DictConverter):
        converter_copy_attrs = [
            # dictionary is not a valid value
            {},
        ]

    with pytest.raises(TypeError, match='Copy field spec is not valid'):
        MyConverter.convert({})


def test_converter_auto_list_detection():
    class EmptyClass:
        pass

    class ConverterA(Converter):
        from_class = EmptyClass
        to_class = EmptyClass

        converter_copy_attrs = [
            ('attr1', {'reverse_attr_name': 'reverse_attr'}),
        ]

    from_instance = EmptyClass()
    from_instance.attr1 = [
        EmptyClass(),
        EmptyClass(),
    ]

    to_inst = ConverterA(from_instance).convert()
    assert_deep_pattern_match(
        list(map(lambda child: child.reverse_attr, to_inst.attr1)), [to_inst, to_inst]
    )


def test_converter_datetime():
    class EmptyClass:
        pass

    class ConverterA(Converter):
        from_class = EmptyClass
        to_class = EmptyClass

        converter_copy_attrs = [
            ('attr1', {'converter': 'datetime'}),
        ]

    from_instance = EmptyClass()
    from_instance.attr1 = '2017-12-26T10:34:16+01:00'
    to_inst = ConverterA(from_instance).convert()
    assert to_inst.attr1 == datetime(2017, 12, 26, 10, 34, 16, tzinfo=timezone(timedelta(hours=1)))


@pytest.fixture
def converter_a():
    class ConverterA(Converter):
        from_class = dict
        to_class = dict

        converter_copy_attrs = [
            ('deep_attr', {'converter': 'ConverterA'}),
            ('numeric_attr', {'converter': lambda attr: attr * 2}),
            ('defaulted_attr', {'default': 'original'}),
        ]
        converter_options = {
            'merge_all': True,
        }

    Converter.register_converter_for_name(ConverterA, 'ConverterA')
    yield ConverterA
    Converter.unregister_converter('ConverterA')


def test_deep_dicts_converter(converter_a):
    d1 = {'deep_attr': {'deep_attr': {'numeric_attr': 4}}}
    converted = converter_a(d1).convert()
    assert_deep_pattern_match(
        converted,
        {
            'deep_attr': {
                'deep_attr': {'numeric_attr': 8, 'defaulted_attr': 'original',},
                'defaulted_attr': 'original',
            },
            'defaulted_attr': 'original',
        },
    )


def test_add_two_extra_args_to_init(converter_a):
    """
    We had a problem with lambda expressions in extra_attrs:
        extra_attrs = [
            (k, NOS, {'default': lambda: v})
            for k, v in getattr(self, 'extra_attrs', {}).items()
        ]

    the lambda expression would return v when invoked, which would then be out of scope.
    """
    d1 = {'deep_attr': {'deep_attr': {'numeric_attr': 4}}}
    converted = converter_a(d1, some_extra_attr='val', some_extra_attr_2='val2').convert()
    assert_deep_pattern_match(
        converted,
        {
            'deep_attr': {
                'deep_attr': {'numeric_attr': 8, 'defaulted_attr': 'original',},
                'defaulted_attr': 'original',
            },
            'some_extra_attr': 'val',
            'some_extra_attr_2': 'val2',
            'defaulted_attr': 'original',
        },
    )


def test_override_default_with_kwargs(converter_a):
    """
    Make sure we respect passing kwargs in as the override.
    """
    converter_inst = converter_a({}, defaulted_attr='new')
    from types import FunctionType

    # Opposed to testing internals, but dynamic_copy_attrs is not an internal:
    # it's a public method that can be used by classes who inherit Converter (e.g.
    # DjangoModelConverter).
    attrs = converter_inst.dynamic_copy_attrs()
    assert_deep_pattern_match(
        attrs,
        [
            # attrs get normalised too
            ('deep_attr', 'deep_attr', {'converter': 'ConverterA'}),
            ('numeric_attr', 'numeric_attr', {'converter': FunctionType}),
            (
                'defaulted_attr',
                'defaulted_attr',
                {'default': 'original', '_kwarg_override': 'new'},
            ),
        ],
    )

    # test converted value is overridden
    converted = converter_inst.convert()
    assert_deep_pattern_match(converted, {'defaulted_attr': 'new'})


def test_add_extra_args_to_init(converter_a):
    d1 = {'deep_attr': {'deep_attr': {'numeric_attr': 4}}}
    converted = converter_a(d1, some_extra_attr='val', some_extra_attr_2='val2').convert()
    assert_deep_pattern_match(
        converted,
        {
            'deep_attr': {
                'deep_attr': {'numeric_attr': 8, 'defaulted_attr': 'original',},
                'defaulted_attr': 'original',
            },
            'some_extra_attr': 'val',
            'some_extra_attr_2': 'val2',
            'defaulted_attr': 'original',
        },
    )


def test_converter_update(converter_a):
    d2 = {}
    d1 = {'deep_attr': d2}

    d_input = {'deep_attr': {'numeric_attr': 5}}

    converted = converter_a(d_input, dest=d1).convert()
    # with a destination we should merge into the existing object tree as
    # merge_all is specified in the converter
    assert converted is d1
    assert converted['deep_attr'] is d2
    assert d2['numeric_attr'] == 10


def test_converter_default_is_limited():
    class BadDefaultSingletonListConverter(DictConverter):
        converter_copy_attrs = [
            ('a', {'default': []}),
        ]

    with pytest.raises(TypeError) as excinfo:
        BadDefaultSingletonListConverter({})
    assert str(excinfo.value) == (
        'default option in converter can only be a callable, number or str. '
        'Default for (a, a) on BadDefaultSingletonListConverter has type "list"'
    )

    class BadDefaultSingletonDictConverter(DictConverter):
        converter_copy_attrs = [
            ('a', 'b', {'default': {}}),
        ]

    with pytest.raises(TypeError) as excinfo:
        BadDefaultSingletonDictConverter({})
    assert str(excinfo.value) == (
        'default option in converter can only be a callable, number or str. '
        'Default for (a, b) on BadDefaultSingletonDictConverter has type "dict"'
    )


def test_deep_converter_set():
    class DeepSettingConverter(Converter):
        from_class = dict
        to_class = dict

        converter_copy_attrs = [
            ('a', {'default': dict}),
            ('a.deep', {'default': dict}),
            ('a.deep.path', 'input_attr'),
            ('a.deep.alternative', 'second_attr'),
        ]

    source = {'input_attr': 'this to be inserted'}
    result = DeepSettingConverter(source).convert()
    assert_deep_pattern_match(result, {'a': {'deep': {'path': 'this to be inserted',}}})

    # run again to ensure that we are setting defaults correctly
    res2 = DeepSettingConverter({'second_attr': 'barmy'}).convert()
    assert_deep_pattern_match(res2, {'a': {'deep': {'alternative': 'barmy',}}})


def test_converter_merge():
    class SubConverter(DictConverter):
        converter_copy_attrs = [
            'a',
            'b',
            'c',
            'd',
            'e',
            'f',
            'g',
        ]

    class TopConverter(DictConverter):
        converter_copy_attrs = [
            ('attr1', SubConverter),
            ('attr2', {'merge': True, 'converter': SubConverter}),
            ('attr_dict', {'merge': True, 'converter': SubConverter}),
        ]

    src = {'attr1': [{'a': 1, 'b': 2}], 'attr2': [{'c': 3, 'd': 4}], 'attr_dict': {'f': 7, 'g': 9}}
    dst = {'attr1': [{'aa': 5}], 'attr2': [{'c': 6, 'e': 7}], 'attr_dict': {'f': 8, 'h': 10}}
    TopConverter.convert(src, dest=dst)
    assert_deep_pattern_match(
        dst,
        {
            'attr1': [{'a': 1, 'b': 2}],
            'attr2': [{'c': 3, 'd': 4, 'e': 7}],
            'attr_dict': {'f': 7, 'g': 9, 'h': 10},
        },
    )


def test_converter_default_if_nos():
    class MyConverter(DictConverter):
        default_if_nos = 'hello world!'
        converter_copy_attrs = [
            ('a', NOS),
        ]

    assert MyConverter.convert({}) == {'a': 'hello world!'}


def test_single_val_filter():
    class MyConverter(DictConverter):
        converter_copy_attrs = [
            ('a', {'filter': lambda a: a % 2 != 0}),
        ]

    assert MyConverter.convert({'a': 4}) == {}
    assert MyConverter.convert({'a': 5}) == {'a': 5}


def test_converter_should_handle_from_class_union_type():
    class MyObject(object):
        def __init__(self):
            self.a = 20

    class MyConverter(Converter):
        from_class = Union[dict, object]
        to_class = MyObject

        converter_copy_attrs = ['a']

    source_dict = {'a': 10}
    result_from_dict: MyObject = MyConverter.convert(source_dict)

    source_obj = MyObject()
    source_obj.a = 10
    result_from_obj: MyObject = MyConverter.convert(source_obj)

    assert result_from_dict.a == 10
    assert result_from_obj.a == 10


def test_converter_should_handle_from_class_union_type_and_copy_to_destination():
    class MyConverter(Converter):
        from_class = Union[dict, object]
        to_class = object

        converter_copy_attrs = ['a']

    class MyObject(object):
        def __init__(self):
            self.a = 20

    destination = {'a': 15}

    # From dict
    source_dict = {'a': 10}

    MyConverter.convert(source_dict, dest=destination)

    assert destination['a'] == 10

    # From object
    source_obj = MyObject()

    MyConverter.convert(source_obj, dest=destination)

    assert destination['a'] == 20


def test_converter_should_handle_from_class_union_type_subclasses():
    class MyObject(object):
        def __init__(self):
            self.a = 20

    class MyChildObject(MyObject):
        pass

    class MyToObject(object):
        def __init__(self):
            self.a = 10

    class MyConverter(Converter):
        from_class = Union[dict, MyObject]
        to_class = MyToObject

        converter_copy_attrs = ['a']

    source = MyChildObject()
    source.a = 15

    result: MyToObject = MyConverter.convert(source)

    assert result.a == 15


@pytest.mark.skipif(
    sys.version_info < (3, 7), reason="Unions in to_class requires python 3.7 or higher"
)
def test_converter_should_raise_exception_on_union_to_class():
    class MyConverter(Converter):
        from_class = dict
        to_class = Union[dict, object]

        converter_copy_attrs = ['a']

    source = {'a': 10}

    with pytest.raises(InvalidToClassException):
        MyConverter(source)


@pytest.mark.parametrize(
    'source, should_raise_exception',
    [
        ({'must_be_present': None, 'must_be_non_none': 'value'}, False),
        (
            {'must_be_present': None, 'must_be_non_none': 'value', 'optional': 'an optionl value'},
            False,
        ),
        ({'must_be_non_none': 'value'}, True),
        ({'must_be_present': 'value', 'must_be_non_none': None}, True),
    ],
)
def test_converter_required_option(source, should_raise_exception):
    class MyConverter(DictConverter):
        converter_copy_attrs = [
            ('must_be_present', {'required': True}),
            ('must_be_non_none', {'required': lambda x: x is not None}),
            ('optional', {'required': False}),
        ]

    with pytest.raises(ValueRequired) if should_raise_exception else nullcontext():
        MyConverter.convert(source)


def test_converter_sort():
    class SortExampleConverter(DictConverter):
        converter_copy_attrs = [
            'no_sort',
            ('nums', {'sort': True}),
            ('dicts', {'sort': itemgetter('name')}),
            ('filter_and_sort', {'filter': lambda x: x >= 5, 'sort': True}),
        ]

    converted = SortExampleConverter(
        {
            'no_sort': [4, 2, 1, 3],
            'nums': [4, 2, 1, 3],
            'dicts': [{'name': 'Bob', 'age': 22,}, {'name': 'Alice', 'age': 33}],
            'filter_and_sort': [4, 9, 5, 1, 3, 7, 0],
        }
    ).convert()

    assert converted['no_sort'] == [4, 2, 1, 3]
    assert converted['nums'] == [1, 2, 3, 4]
    assert converted['dicts'][0]['name'] == 'Alice'
    assert converted['dicts'][1]['name'] == 'Bob'
    assert converted['filter_and_sort'] == [5, 7, 9]


def test_converter_context(snapshot):
    class MySubConverter(DictConverter):
        converter_copy_attrs = [
            'not_from_context',
            'from_context',
            ('val1', 'from_built_context.val1'),
            ('derived_from_context', 'not_from_context', 'method_using_context'),
        ]

        def method_using_context(self, val):
            cval = self.context.get('from_context')
            if cval is None:
                return None
            return cval * val

    class MyConverter(DictConverter):
        converter_copy_attrs = [
            'from_context',
            'overridden_by_source',
            ('subs', MySubConverter),
            ('merged_result', 'subs', 'method_merging_contexts'),
        ]

        def build_context(self):
            return {'from_built_context': {'val1': 17}, 'not_from_context': 'this is overridden'}

        def method_merging_contexts(self, val):
            return MySubConverter.convert(val, context={'from_context': 9})

    assert snapshot == MyConverter.convert(
        {'overridden_by_source': 3, 'subs': [{'not_from_context': 4}]},
        context={'from_context': 7, 'overridden_by_source': 7},
    )

    # just verify that the context is clear the second time through (though not the nested context)
    assert snapshot == MyConverter.convert(
        {'overridden_by_source': 3, 'subs': [{'not_from_context': 4}]}
    )
