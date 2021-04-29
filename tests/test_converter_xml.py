import pytest
from lxml import etree

from converters import NOS, Converter
from converters.contrib.xml import XMLConverter

from ._test_utils import assert_deep_pattern_match


class PackageFromXMLConverter(XMLConverter):
    to_class = dict
    conversions = [
        'weight',
    ]


class PackageToXMLConverter(XMLConverter):
    from_class = dict
    conversions = [
        'weight',
    ]


shared_conversions = [
    ('consignment.reference', 'reference'),
    (
        'consignment.consignmentIdentity.attr1',
        'sourceattr',
        {'xml_type': 'attr', 'default': 'shouldntusedefault'},
    ),
    ('consignment.consignmentIdentity.attr2', NOS, ({'xml_type': 'attr', 'default': 'use'}),),
    ('consignment.consignmentIdentity.consignmentNumber', 'number'),
    ('consignment.consignmentIdentity.textValue', NOS, {'default': 'textval'}),
    # Write out longhand so conversions for converter_from_xml works simply
    (
        'consignment.consignmentIdentity.emptyValue',
        'consignment.consignmentIdentity.emptyValue',
        {'default': ''},
    ),
    # Add an empty node by using the `default_if_nos` switch
    ('consignment.empty', NOS),
]


@pytest.fixture
def converter_to_xml():
    class ConverterToXML(XMLConverter):
        from_class = dict
        root_key = 'labelResponse'

        conversions = [
            *shared_conversions,
            ('consignment.package', 'packages', PackageToXMLConverter),
        ]

    Converter.register_converter_for_name(ConverterToXML, 'ConverterToXML')
    try:
        yield ConverterToXML
    finally:
        Converter.unregister_converter('ConverterToXML')


@pytest.fixture
def converter_to_xml_without_cdata():
    class ConverterToXML(XMLConverter):
        from_class = dict
        root_key = 'labelResponse'

        converter_options = {
            'use_cdata': False,
        }
        conversions = [
            *shared_conversions,
            ('consignment.package', 'packages', PackageToXMLConverter),
        ]

    Converter.register_converter_for_name(ConverterToXML, 'ConverterToXML')
    try:
        yield ConverterToXML
    finally:
        Converter.unregister_converter('ConverterToXML')


@pytest.fixture
def converter_from_xml():
    class ConverterFromXML(XMLConverter):
        to_class = dict

        conversions = [
            *[
                (k[1], k[0], k[2] if len(k) > 2 else {})
                for k in shared_conversions
                if k[1] != NOS
            ],
            (
                'packages',
                'consignment.package',
                {'converter': PackageFromXMLConverter, 'xml_type': 'list'},
            ),
        ]

    Converter.register_converter_for_name(ConverterFromXML, 'ConverterFromXML')
    yield ConverterFromXML
    Converter.unregister_converter('ConverterFromXML')


def test_to_xml_converter(converter_to_xml):
    d1 = {
        'reference': 'TestRef',
        'sourceattr': 'attrval',
        'number': '1234',
        'packages': [{'weight': 5}, {'weight': 7}],
    }
    root = converter_to_xml(d1).convert()
    assert root.tag == 'labelResponse'
    consignment = root.find('consignment')
    assert consignment.tag == 'consignment'
    assert consignment.find('reference').text == 'TestRef'
    consignment_identity = consignment.find('consignmentIdentity')
    assert consignment_identity.tag == 'consignmentIdentity'
    assert consignment_identity.get('attr1') == 'attrval'
    assert consignment_identity.get('attr2') == 'use'
    assert consignment_identity.find('consignmentNumber').text == '1234'
    assert consignment_identity.find('textValue').text == 'textval'
    assert not consignment_identity.find('emptyValue').text
    packages = consignment.findall('package')
    weights = [i.find('weight').text for i in packages]
    assert '5' in weights
    assert '7' in weights
    assert etree.tostring(root).decode('utf-8') == (
        '<labelResponse><consignment><reference><![CDATA[TestRef]]>'
        '</reference><consignmentIdentity attr1="attrval" attr2="use"><consignmentNumber>'
        '<![CDATA[1234]]>'
        '</consignmentNumber><textValue><![CDATA[textval]]></textValue><emptyValue><![CDATA[]]>'
        '</emptyValue>'
        '</consignmentIdentity><empty/><package><weight><![CDATA[5]]></weight></package><package>'
        '<weight><![CDATA[7]]>'
        '</weight></package></consignment></labelResponse>'
    )


def test_to_xml_converter_no_cdata(converter_to_xml_without_cdata):
    d1 = {
        'reference': 'TestRef',
        'sourceattr': 'attrval',
        'number': '1234',
        'packages': [{'weight': 5}, {'weight': 7}],
    }
    root = converter_to_xml_without_cdata(d1).convert()
    assert etree.tostring(root).decode('utf-8') == (
        '<labelResponse><consignment><reference>TestRef</reference><consignmentIdentity '
        'attr1="attrval" attr2="use">'
        '<consignmentNumber>1234</consignmentNumber><textValue>textval</textValue><emptyValue>'
        '</emptyValue>'
        '</consignmentIdentity><empty/><package><weight><![CDATA[5]]></weight></package><package>'
        '<weight><![CDATA[7]]>'
        '</weight></package></consignment></labelResponse>'
    )


def test_from_xml_converter(converter_from_xml):
    xml = etree.XML(
        b"""<?xml version="1.0" encoding="UTF-8"?>
    <labelResponse>
        <consignment>
            <reference>TestRef</reference>
            <consignmentIdentity attr1="attrval" attr2="use">
                <consignmentNumber>1234</consignmentNumber>
                <textValue>textval</textValue>
                <emptyValue />
            </consignmentIdentity>
            <package>
                <weight>5</weight>
            </package>
            <package>
                <weight>7</weight>
            </package>
        </consignment>
    </labelResponse>
    """
    )
    root = converter_from_xml(xml).convert()
    assert_deep_pattern_match(
        root,
        {
            'reference': 'TestRef',
            'sourceattr': 'attrval',
            'number': '1234',
            'packages': [{'weight': '5'}, {'weight': '7'}],
        },
    )


def test_from_xml_converter_with_single_item_in_list(converter_from_xml):
    """
    There was a bug that returned just an object rather than a list of one object for
    a single node that could've been multiple, ie package here.
    """
    xml = etree.XML(
        b"""<?xml version="1.0" encoding="UTF-8"?>
    <labelResponse>
        <consignment>
            <reference>TestRef</reference>
            <consignmentIdentity attr1="attrval" attr2="use">
                <consignmentNumber>1234</consignmentNumber>
                <textValue>textval</textValue>
                <emptyValue />
            </consignmentIdentity>
            <package>
                <weight>5</weight>
            </package>
        </consignment>
    </labelResponse>
    """
    )
    root = converter_from_xml(xml).convert()
    assert_deep_pattern_match(
        root,
        {
            'reference': 'TestRef',
            'sourceattr': 'attrval',
            'number': '1234',
            'packages': [{'weight': '5'}],
        },
    )
