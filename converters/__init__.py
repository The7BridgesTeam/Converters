"""The core module.

.. rubric:: Classes

.. autosummary::
   :toctree: converters
   :nosignatures:

   Converter
   DictConverter

"""
NOS = '--Not On Source--'
"""The "Not On Source" attribute indicator.

Use this in place of a source attribute in a conversion specification to set an attribute on the
target object that does not come from an attribute on the source but instead is a constant or
is created by a factory function.

So for example::

    conversions = [
        ("a", NOS, "the default"),
    ]

Attribute ``"a"`` is set to be the string ``"the default"`` on the destination object, without
fetching anything from the source.
"""

from .converter import Converter, DictConverter, InvalidToClassException, NOS, ValueRequired

__all__ = ['Converter', 'DictConverter', 'InvalidToClassException', 'NOS', 'ValueRequired']

try:
    import dateutil
    import pytz
except ImportError:
    pass
else:
    from .contrib.datetime import *
    __all__ += exports
