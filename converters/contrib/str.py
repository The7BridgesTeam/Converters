import logging
from collections.abc import Iterable

from converters import Converter


__all__ = ['StrConverter']

log = logging.getLogger(__name__)


class StrConverter(Converter):
    """Converter
    class to convert things to strings.

    # Example Usage

        >>> class MyStrConverter(StrConverter):
        ...     from_class = dict
        ...     conversions = [
        ...         'attr1',
        ...         # this one takes its value from 'attr2' and uses None as the to_attr
        ...         # since obviously you can't set attributes on strings.
        ...         (None, 'attr2', lambda st: st.upper()),
        ...         lambda _: 'a constant string',
        ...         lambda _: 'another constant string',
        ...         'list_attr',
        ...     ]
        ...     converter_options = {
        ...         'join_string': ', '
        ...     }
        >>> MyStrConverter({
        ...     'attr1': 'some value', 'attr2': 'another value',
        ...     'list_attr': ['also', 'these']
        ... }).convert()
        'some value, ANOTHER VALUE, a constant string, another constant string, also, these'
    """

    to_class = str

    converter_options = {
        'pass_attrs_to_init': True,
        # this is the string that is inserted between each attribute
        'join_string': '',
        'text_transformer': None,
    }

    def instantiate(self, dct):
        tf = self._resolved_converter_options['text_transformer']
        result = self._resolved_converter_options['join_string'].join(
            value if tf is None else tf(value)
            for list_value in (
                [val] if isinstance(val, str) or not isinstance(val, Iterable) else val
                for val in (val_and_opts[0] for _, val_and_opts in dct.items())
                if val is not None
            )
            for value in list_value
        )
        return result


class UpperStrConverter(StrConverter):
    """A convenience subclass of `StrConverter` to end with an entirely uppercase string."""

    converter_options = {
        'text_transformer': lambda st: st.upper(),
    }
