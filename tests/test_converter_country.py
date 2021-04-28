import pytest

from converters.contrib.country import convert_to_country_code


@pytest.mark.parametrize(
    'name, code',
    [
        ('United Kingdom', 'GB'),
        (' great britain ', 'GB'),
        ('UK', 'GB'),
        ('Germany', 'DE'),
        ('South Georgia And The \t South Sandwich Islands', 'GS'),
        ('Kosovo', 'XK'),
        ('Åland Islands', 'AX'),
        ('Aland Islands', 'AX'),
        ('Czechia', 'CZ'),
        ('Czech Republic', 'CZ'),
        ('Taiwan, China', 'TW'),
        ('Korea (the Republic of)', 'KR'),
        ('Korea, South', 'KR'),
        ('South Korea', 'KR'),
        ('GB', 'GB'),
        ('fr', 'FR'),
        (' Nl\t', 'NL'),
        ('GBR', 'GB'),
        ('   ', ''),
        (None, ''),
    ],
)
def test_convert_to_country_code(name, code):
    assert convert_to_country_code(name) == code


def test_converter_country(mocker):
    cc_log = mocker.patch('converters.contrib.country.log')
    for code, result in [
        ('US', 'US'),
        ('USA', 'US'),
        ('GB', 'GB'),
        ('GBR', 'GB'),
        ('United Kingdom', 'GB'),
        # this is not a valid alpha3 code
        ('GBX', ''),
    ]:
        assert convert_to_country_code(code) == result
    assert cc_log.warning.call_args_list == [
        mocker.call('Could not determine country code of %r', 'GBX')
    ]
