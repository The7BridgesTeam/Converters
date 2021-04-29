from django.db.models import CharField, Model

import pytest
from pytest import param

from converters.contrib.django_model import AutoDjangoModelConverter

from .django.django_app.models import DjangoModelConverterTestModel, DMCTestParentModel


@pytest.fixture
def test_model():
    class TestModel(Model):
        class Meta:
            app_label = 'django_app'
        field1 = CharField(max_length=128)
        field2 = CharField(max_length=128)

    return TestModel


@pytest.fixture
def test_model_copier(test_model):
    class TestModelCopier(AutoDjangoModelConverter):
        from_class = test_model
        to_class = test_model

        conversions = [
            # this overrides the default behaviour for field2
            ('field2', {'converter': lambda x: x + ' extra'})
        ]
        converter_options = dict(AutoDjangoModelConverter.converter_options)
        converter_options.update(
            {'django_model_converter_save': False,}
        )

    return TestModelCopier


def test_django_converter(test_model, test_model_copier):
    inst = test_model(field1='some text', field2='this has')
    inst2 = test_model_copier(inst).convert()
    assert inst2.field1 == 'some text'
    assert inst2.field2 == 'this has extra'


@pytest.mark.django_db
def test_django_converter_convert_file_field():
    class DMC(AutoDjangoModelConverter):
        from_class = dict
        to_class = DjangoModelConverterTestModel

        conversions = [
            'a_file',
        ]

    tm1 = DMC.convert({'a_file': b'file contents'})
    tm1 = DjangoModelConverterTestModel.objects.get(id=tm1.id)

    assert tm1.a_file.read() == b'file contents'
    assert tm1.a_file.url.endswith('.a_file')

    tm2 = DMC.convert({'a_file': 'ßpooky unicode 😀'})
    tm2 = DjangoModelConverterTestModel.objects.get(id=tm2.id)

    assert tm2.a_file.read().decode() == 'ßpooky unicode 😀'
    assert tm2.a_file.url.endswith('.a_file')


@pytest.mark.django_db
@pytest.mark.parametrize(
    'extension, filename_assert',
    [
        param('txt', lambda fn: fn.endswith('.txt'), id='.txt'),
        param('.pdf', lambda fn: fn.endswith('.pdf'), id='.pdf'),
        param('tar.gz', lambda fn: fn.endswith('.tar.gz'), id='.tar.gz'),
        param('', lambda fn: '.' not in fn, id='no-extension'),
    ],
)
def test_django_converter_convert_file_field_with_extension(extension, filename_assert):
    class DMC(AutoDjangoModelConverter):
        from_class = dict
        to_class = DjangoModelConverterTestModel

        conversions = [
            ('a_file', {'file_extension': extension}),
        ]

    tm1 = DMC.convert({'a_file': b'file contents'})
    tm1 = DjangoModelConverterTestModel.objects.get(id=tm1.id)
    if not filename_assert(tm1.a_file.url):
        import pdb
        pdb.set_trace()
    assert filename_assert(tm1.a_file.url)


@pytest.mark.django_db
def test_parent_child_shallow_conversion():
    class ShallowParentConverter(AutoDjangoModelConverter):
        from_class = DMCTestParentModel
        to_class = DMCTestParentModel

    parent = DMCTestParentModel.objects.create(parent_text='This is the parent text')
    DjangoModelConverterTestModel.objects.create(parent=parent, child_text='Child 1 text')
    DjangoModelConverterTestModel.objects.create(parent=parent, child_text='Child 2 text')

    par2 = ShallowParentConverter.convert(parent)
    assert par2.parent_text == 'This is the parent text'
    assert par2.children.count() == 0


@pytest.mark.django_db
def test_parent_child_deep_conversion():
    class DeepParentConverter(AutoDjangoModelConverter):
        from_class = DMCTestParentModel
        to_class = DMCTestParentModel
        conversions = ['children']

    parent = DMCTestParentModel.objects.create(parent_text='This is the parent text')
    DjangoModelConverterTestModel.objects.create(parent=parent, child_text='Child 1 text')
    DjangoModelConverterTestModel.objects.create(parent=parent, child_text='Child 2 text')

    par2 = DeepParentConverter.convert(parent)
    assert par2.id != parent.id
    assert par2.parent_text == 'This is the parent text'
    assert parent.children.count() == 0
    assert par2.children.count() == 2
    assert ', '.join(c.child_text for c in par2.children.order_by('child_text')) == (
        'Child 1 text, Child 2 text'
    )


@pytest.mark.django_db
def test_parent_child_deep_copy_conversion():
    class ChildConverter(AutoDjangoModelConverter):
        from_class = DjangoModelConverterTestModel
        to_class = DjangoModelConverterTestModel

    class DeepCopyingParentConverter(AutoDjangoModelConverter):
        from_class = DMCTestParentModel
        to_class = DMCTestParentModel
        conversions = [
            ('children', ChildConverter),
        ]

    parent = DMCTestParentModel.objects.create(parent_text='This is the parent text')
    DjangoModelConverterTestModel.objects.create(parent=parent, child_text='Child 1 text')
    DjangoModelConverterTestModel.objects.create(parent=parent, child_text='Child 2 text')

    par2 = DeepCopyingParentConverter.convert(parent)
    assert par2.id != parent.id
    assert par2.parent_text == 'This is the parent text'
    assert parent.children.count() == 2
    assert par2.children.count() == 2
    assert ', '.join(c.child_text for c in par2.children.order_by('child_text')) == (
        'Child 1 text, Child 2 text'
    )
