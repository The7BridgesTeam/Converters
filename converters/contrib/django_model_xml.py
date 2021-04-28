from unidecode import unidecode

from .django_model import DjangoModelConverter
from .xml import XMLConverter


class DjangoModelXMLConverter(DjangoModelConverter, XMLConverter):
    converter_options = {'convert_nones_to_blanks': True}


class ASCIIDjangoModelXMLConverter(DjangoModelXMLConverter):
    converter_washers = {str: unidecode}
