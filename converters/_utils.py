import sys
from typing import Callable, Union

from pydash import merge


# --------------------------------------------------------------------------------------------------
# Decorators
# --------------------------------------------------------------------------------------------------
class class_or_instance_method:  # noqa
    """This decorator allows you to make a method act on a class or an
    instance. So:

    >>> class MyClass(object):
    ...     @class_or_instance_method
    ...     def add_property(cls_or_self, prop, val):
    ...         setattr(cls_or_self, prop, val)
    >>> MyClass.a
    Traceback (most recent call last):
    ...
    AttributeError: type object 'MyClass' has no attribute 'a'
    >>> MyClass.add_property('a', 1)
    >>> MyClass.a
    1
    >>> inst = MyClass()
    >>> inst.a
    1
    >>> inst.b
    Traceback (most recent call last):
    ...
    AttributeError: 'MyClass' object has no attribute 'b'
    >>> inst.add_property('b', 2)
    >>> inst.b
    2
    >>> MyClass.b
    Traceback (most recent call last):
    ...
    AttributeError: type object 'MyClass' has no attribute 'b'
    """

    def __init__(self, func):
        self._func = func

    def __get__(self, obj, cls):
        target = obj if obj is not None else cls

        def class_or_instance_wrapper(*args, **kwargs):
            return self._func(target, *args, **kwargs)

        return class_or_instance_wrapper


# --------------------------------------------------------------------------------------------------
# Descriptors
# --------------------------------------------------------------------------------------------------
class MergedClassProperty:
    def __init__(self, class_property):
        self.class_property = class_property
        self.class_cache_property = f'__{class_property}_cache'

    def __get__(self, instance, cls):
        # need to get it direct in case a superclass has it set differently
        cached_result = cls.__dict__.get(self.class_cache_property)
        if cached_result is not None:
            return cached_result

        merged_prop = merge(
            {},
            *(getattr(super_class, self.class_property, {}) for super_class in cls.__mro__[-1::-1]),
        )
        setattr(cls, self.class_cache_property, merged_prop)
        return merged_prop


# --------------------------------------------------------------------------------------------------
# Functions
# --------------------------------------------------------------------------------------------------
def cn(obj):
    if isinstance(obj, type):
        return obj.__name__
    return type(obj).__name__


def identity(arg):
    return arg


def infinite_counter(initial=1, increment=1):
    counter = initial
    while True:
        yield counter
        counter += increment


def yield_forever(value):
    while True:
        yield value


def is_union_type(tp):
    if sys.version_info[:3] >= (3, 7, 0):  # PEP 560
        from typing import _GenericAlias
        return tp is Union or isinstance(tp, _GenericAlias) and tp.__origin__ is Union

    __origin__ = getattr(tp, '__origin__', False)
    return tp is typing.Union or __origin__ and __origin__ is Union


def is_one_of_union_types(source, union: Union):
    return any(type(source) is ut or isinstance(source, ut) for ut in union.__args__)
