from collections.abc import Iterable
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
from difflib import unified_diff


def ud(a, b):
    try:
        return list(unified_diff(a, b))
    except TypeError:
        # ud doesn't compare types well
        return f'{unpack_to_str(a)} != {unpack_to_str(b)}'


def unpack_to_str(list_to_unpack):
    return '[{}]'.format(', '.join(map(str, list_to_unpack)))


def assert_deep_pattern_match(a, b, stack=None, **opts):
    """
    Throws an AssertionError if a does not match b.
    a = test against
    b = to test for

    >>> assert_deep_pattern_match(
    ...     {'a': {'b': {'c': 1}}},
    ...     {'a': {'b': {'c': 2}}}
    ... )
    Traceback (most recent call last):
     ...
    AssertionError: (['a', 'b', 'c'], 1, 2)

    throws a helpful error if types mismatch
    >>> assert_deep_pattern_match({'key': [{'int': 2}]}, {'key': [{'int': 'str'}]})
    Traceback (most recent call last):
     ...
    AssertionError: (['key', 0, 'int'], 2, 'str')

    ignore_ordering can be passed to ignore the ordering of array elements:

    incorrect ordering should raise by default
    >>> assert_deep_pattern_match([1, 2], [2, 1])
    Traceback (most recent call last):
     ...
    AssertionError: ([0], 1, 2)

    >>> assert_deep_pattern_match([1, 2], [2, 1], ignore_ordering=True)

    should recursively ignore
    >>> assert_deep_pattern_match(
    ...     {'key': [{'int': 2}, {'other': 1}]},
    ...     {'key': [{'other': 1}, {'int': 2}]},
    ...     ignore_ordering=True)

    should work for an array of maps
    >>> assert_deep_pattern_match(
    ...     [{'first': 'obj'}, {'second': 'obj'}],
    ...     [{'second': 'obj'}, {'first': 'obj'}],
    ...     ignore_ordering=True
    ... )

    should check for repeated values
    >>> assert_deep_pattern_match([1, 2], [2, 2], ignore_ordering=True)
    Traceback (most recent call last):
     ...
    AssertionError: [[0]] elements not found in RHS, first missing element (at [0]): 1

    throws a helpful error if types mismatch when ignore_ordering=True
    >>> assert_deep_pattern_match(
    ...     {'key': [{'int': 2}]}, {'key': [{'int': 'str'}]},
    ...     ignore_ordering=True
    ... )
    Traceback (most recent call last):
     ...
    AssertionError: ['key', [0]] elements not found in RHS, first missing element (at [0]): \
{'int': 2}


    subset can be passed to note b is a subset of a
    >>> assert_deep_pattern_match({'key1': 'val', 'key2': 'val'}, {'key1': 'val'}, subset=True)

    subset should work recursively
    >>> assert_deep_pattern_match(
    ...     {'key1': 'val', 'key2': {'1': 1, '2': 2}}, {'key2': {'2': 2}},
    ...     subset=True
    ... )

    subset SHOULDN'T ignore ordering on deep lists
    >>> assert_deep_pattern_match({'list': [1, 2]}, {'list': [2, 1]}, subset=True)
    Traceback (most recent call last):
     ...
    AssertionError: (['list', 0], 1, 2)

    but subset SHOULD ignore ordering on deep lists if ignore_ordering=True
    >>> assert_deep_pattern_match(
    ...     {'list': [1, 2], 'other': 'val'},
    ...     {'list': [2, 1]},
    ...     subset=True, ignore_ordering=True)

    and should work recursively
    >>> assert_deep_pattern_match(
    ...     [{'int': 2, 'another_key': 1}, {'other': 1}],
    ...     [{'other': 1}, {'int': 2}],
    ...     subset=True, ignore_ordering=True)

    subset should NOT apply to lists because we want to check lists match if we're testing
     a subset of keys, ie
    >>> assert_deep_pattern_match({'k': [1, 2], 'l': 1}, {'k': [1, 2]}, subset=True)
    >>> assert_deep_pattern_match([1, 2], [1], subset=True)
    Traceback (most recent call last):
     ...
    AssertionError: ([], 2, 1, '[1, 2] != [1]')

    NOTE that in the future we could add another kwarg to add this functionality.

    subset should NOT apply to deep lists
    >>> assert_deep_pattern_match(
    ...     {'key': [{'int': 2}]}, {'key': [{'other': 1}, {'int': 2}]},
    ...     subset=True
    ... )
    Traceback (most recent call last):
     ...
    AssertionError: (['key'], 1, 2, "[{'int': 2}] != [{'other': 1}, {'int': 2}]")

    """
    stack = stack or []
    opts = opts or {}

    if isinstance(b, type):
        assert isinstance(a, b), (stack, a, b)
        return

    # useful to validate data that needs the right shape but not exact values
    if isinstance(a, dict):
        assert isinstance(b, dict), (stack, a, b)
        a_keys, b_keys = (list(sorted(a.keys())), list(sorted(b.keys())))
        if opts.get('subset'):
            assert set(a_keys) >= set(b_keys), (stack, ud(a_keys, b_keys))
        else:
            assert a_keys == b_keys, (stack, ud(a_keys, b_keys))

        for key in b_keys:
            assert_deep_pattern_match(a[key], b[key], stack=[*stack, key], **opts)

    elif isinstance(a, str):
        if isinstance(b, str):
            assert a == b, (stack, a, b)

        else:
            assert isinstance(b, type(test_regex)), (stack, a, b)
            assert b.match(a) is not None, (stack, a, b)

    elif isinstance(a, bytes):
        if isinstance(b, bytes):
            assert a == b, (stack, a, b)

        else:
            assert isinstance(b, type(test_regex)), (stack, a, b)
            assert b.match(a) is not None, (stack, a, b)

    elif isinstance(a, Iterable):
        assert isinstance(b, Iterable), (stack, ud(a, b))
        assert len(a) == len(b), (stack, len(a), len(b), ud(a, b))
        if opts.get('ignore_ordering'):
            # copy so we can remove items to test against duplicates
            a_list = list(a)
            a_copy = deepcopy(a_list)
            found_a_elements = []
            # iterate over the elements in b and check they exist in a
            # if there are duplicate elements in b, check there are the same number of duplicates
            #  in a by removing elements in a_copy when we find a match
            # if a_copy has elements left over after matching all b elements, and we haven't
            #  passed opts.subset=True, then raise
            # NOTE that we don't need to check elements of a are in b due to removing
            #  elements on match and checking the length of a after matching
            for (indb, subb) in enumerate(b):
                for (inda, suba) in enumerate(a_copy):
                    try:
                        # test b against a in case subset=True was passed
                        assert_deep_pattern_match(suba, subb, stack=[*stack, indb], **opts)
                        a_copy.pop(inda)
                        found_a_elements.append(inda)
                        break
                    except AssertionError:
                        pass

            if len(found_a_elements) != len(a_list):
                missing_indices = [x for x in range(len(a_list)) if x not in found_a_elements]
                raise AssertionError(
                    f'{stack + [missing_indices]} elements not found in RHS, first missing '
                    f'element (at [{missing_indices[0]}]): {a_list[missing_indices[0]]}'
                )

        else:
            for (ind, (suba, subb)) in enumerate(zip(a, b)):
                assert_deep_pattern_match(suba, subb, stack=[*stack, ind], **opts)

    else:
        a_normed = float(a) if isinstance(a, Decimal) else a
        b_normed = float(b) if isinstance(b, Decimal) else b
        assert a_normed == b_normed, (stack, a, b)


# Shamelessly stolen from Python 3.7
@contextmanager
def nullcontext(enter_result=None):
    yield enter_result
