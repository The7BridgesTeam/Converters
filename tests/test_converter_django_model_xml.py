from django.db.models import CharField, Model

import pytest
from lxml import etree

from converters import Converter
from converters.contrib.django_model_xml import DjangoModelXMLConverter


@pytest.fixture
def test_model():
    class TestModelTwo(Model):
        class Meta:
            app_label = 'django_app'
        field1 = CharField(max_length=128)
        field2 = CharField(max_length=128)
        # By default shouldn't add these extra fields not defined in conversions (distinct
        # from the default behaviour in DjangoModelConverter)
        field3 = CharField(max_length=128)

    return TestModelTwo


@pytest.fixture
def model_converter_to_xml(test_model):
    class ConverterToXML(DjangoModelXMLConverter):
        from_class = test_model
        to_class = etree._Element

        conversions = [
            'field1',
            ('field2to', 'field2'),
        ]

        converter_options = dict(DjangoModelXMLConverter.converter_options)
        converter_options.update(
            {'django_model_converter_save': False,}
        )

    Converter.register_converter_for_name(ConverterToXML, 'ConverterToXML')
    yield ConverterToXML
    Converter.unregister_converter('ConverterToXML')


def test_django_to_xml_converter(test_model, model_converter_to_xml):
    inst = test_model(field1='some text', field2='this has')
    xml = model_converter_to_xml(inst).convert()
    assert etree.tostring(xml).decode('utf-8') == (
        '<root>'
        '<field1><![CDATA[some text]]></field1><field2to><![CDATA[this has]]></field2to>'
        '</root>'
    )
