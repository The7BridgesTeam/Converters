from lxml import etree  # nosec

from ..converter import Converter


def to_xml_getter(inst, attr, val, opts, right=None):
    if attr == 'self':
        return inst

    if opts.get('xml_type') == 'attr' and not right:
        return inst.get(attr)

    val = inst.find(attr)
    if etree.iselement(val):
        return val

    val = etree.SubElement(inst, attr)

    return val


def from_xml_getter(inst, attr, default_val, opts):
    if attr == 'self':
        return inst

    left, _, right = attr.partition('.')

    if opts.get('xml_type') == 'attr' and not right:
        return inst.get(attr)

    vals = inst.findall(left)
    if len(vals) == 0:
        return default_val

    val = vals[0]
    if right:
        # Still more of path
        if len(vals) > 1:
            return [from_xml_getter(v, right, default_val, opts) for v in vals]
        return from_xml_getter(val, right, default_val, opts)

    # Check if we're the last element (to get text) or if we have children (return dict)
    if len(val) == 0:
        return val.text

    # Has children
    if len(vals) > 1 or opts.get('xml_type') == 'list':
        return vals
    return val


class XMLConverter(Converter):
    """Converter
    class to convert things to and from `lxml`'s representations.

    # Example usage

        >>> from lxml import etree
        >>> class MyXMLConverter(XMLConverter):
        ...     from_class = dict
        ...     root_key = 'document'
        ...     conversions = [
        ...         ('h1', 'heading'),
        ...         ('h1.class', 'heading_class', {'xml_type': 'attr'}),
        ...         ('element', 'elements'),
        ...     ]
        ...     converter_options = { 'use_cdata': False }

        >>> etree.tostring(  # doctest: +NORMALIZE_WHITESPACE
        ...     MyXMLConverter({
        ...         'heading': 'Hello world', 'heading_class': 'very-important',
        ...         'elements': [1, 2],
        ...     }).convert()
        ... )
        b'<document><h1 class="very-important">Hello
        world</h1><element>1</element><element>2</element></document>'
    """

    from_class = etree._Element
    to_class = etree._Element

    @staticmethod
    def default_if_nos():
        return etree.Element('shouldbeoverwrittenbydestname')

    root_key = 'root'

    converter_options = {
        'use_cdata': True,
    }

    @property
    def _from_is_xml(self):
        return self.from_class == etree._Element

    @property
    def _to_is_xml(self):
        return self.to_class == etree._Element

    def __init__(self, source, parent=None, **kwargs):
        self.parent = parent

        if self._from_is_xml:
            if self.root_key and etree.iselement(source.find(self.root_key)):
                source = source.find(self.root_key)

        super().__init__(source, **kwargs)

    # As lxml's etree can't use pydash's `get` and python's `set_`, we need to override the getters
    # and setters for Converter
    @property
    def setter(self):
        if self._to_is_xml:
            return self.xml_setter
        return self.default_setter

    @property
    def from_getter(self):
        if self._from_is_xml:
            return from_xml_getter
        return self.default_getter

    @property
    def to_getter(self):
        if self._to_is_xml:
            return to_xml_getter
        return self.default_getter

    def val_is_collection(self, val):
        return not isinstance(val, etree._Element) and super().val_is_collection(val)

    def dynamic_copy_attrs(self):
        attrs = list(self.normalize_copy_attrs(super().dynamic_copy_attrs()))
        for (t, s, opts) in attrs:
            opts.setdefault('use_cdata', self._resolved_converter_options['use_cdata'])
        return attrs

    def xml_setter(self, inst, attr, val, opts):
        if opts.get('xml_type') == 'attr':
            inst.set(attr, val)
        else:
            if isinstance(val, list):
                for v in val:
                    self._set_value(inst, attr, opts, v)
            elif etree.iselement(val):
                val.tag = attr
                inst.append(val)
            else:
                ele = etree.SubElement(inst, attr)
                if opts.get('use_cdata'):
                    ele.text = etree.CDATA(str(val))
                else:
                    ele.text = str(val)
        return inst

    def instantiate(self, dct):
        if self._to_is_xml:
            if self.parent is not None:
                ele = etree.SubElement(self.parent, self.root_key)
            else:
                ele = etree.Element(self.root_key)
            self.populate_instance(ele, dct)
            return ele
        return super().instantiate(dct)
