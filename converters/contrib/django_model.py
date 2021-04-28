import logging
from typing import List, Optional, Union

from django.core.files.base import ContentFile
from django.db.models import FileField, ManyToManyField, Model
from django.db.models.fields.files import FieldFile
from django.db.models.fields.related import ManyToManyRel, ManyToOneRel, OneToOneRel
from django.db.models.fields.reverse_related import ForeignObjectRel
from django.db.transaction import atomic

from ..converter import _SENTRY, DEDUPE_ALL, NOS, Converter


__all__ = ['DjangoModelConverter']
log = logging.getLogger(__name__)


class DjangoModelConverter(Converter):
    """Convert
    to and from django models.

    The main things this provides are:

    - Correct handling of model relationships
    - Automatic saving of source data to `FileField`s.
    - Detection of fields to copy based on the models passed in.
    - On by default saving of the instance on creating / modifying it

    More details below.

    ### `FileField` support

    If you have a model

        class MyModel(Model):
            a_file = FileField()

    And you create a converter:

        class MyModelConverter(DjangoModelConverter):
            from_class = dict
            to_class = MyModel

    By default this will save the contents of the source `a_file` attribute
    directly to file. So:

        inst = MyModelConverter.convert({'a_file': 'this text will go into the file'})
        inst.a_file.read() == b'this text will go into the file'

    If setting the file contents through a string or bytes object, as in the
    example above, the default file extension will be the field name. If you
    want to change that, use the `file_extension` option to set a specific
    value:

        class MyModelConverter(DjangoModelConverter):
            from_class = dict
            to_class = MyModel

            converter_copy_attrs = [
                ('a_file', {'file_extension': 'txt'}),
            ]

        inst = MyModelConverter.convert({'a_file': 'this text will go into the file'})
        assert inst.a_file.url.endswith('.txt')

    To remove it altogether, just use an empty string: `{'file_extension': ''}`.

    ### Automatic field copying.

    This behaviour is off by default, but you can add
    `converter_options = {'django_model_add_fields_to_copy_attrs': True}`
    to enable it, or (recommeded) inherit from `AutoDjangoModelConverter` instead.

    The fields that are automatially added will be from the `to_class`, if it
    is a model, else from the `from_class`. One of the `to_class` or `from_class`
    needs to be a model (subclass of `django.db.models.Model`).

    Creating to-many relationships from to-many relationships is not automatically
    done, because often that's not what is wanted, and it can break existing
    relationships. If it is, then you can specify those fields in
    `converter_copy_attrs` to enable them.

    So for example:

        class ChildModel(Model):
            child_text = TextField()
            parent = ForeignKey('ParentModel', related_name='children')

        class ParentModel(Model):
            parent_text = TextField()

        class ShallowParentCopier(AutoDjangoModelConverter):
            from_class = ParentModel
            to_class = ParentModel

    Since `ShallowParentCopier` does not specify recursing to the child model,
    if you do:

        parent = ParentModel.objects.create(parent_text='Parent text')
        ChildModel.objects.create(parent=parent, child_text='Child 1 text')
        ChildModel.objects.create(parent=parent, child_text='Child 2 text')
        ShallowParentCopier.convert(parent)

    You just end up with a single row in the `ParentModel` table. However, you
    can assign over the children if you specify the `'children'` attribute
    to recurse through:

        class DeepParentConverter(AutoDjangoModelConverter):
            from_class = ParentModel
            to_class = ParentModel
            converter_copy_attrs = [
                'children'
            ]

        DeepParentConverter.convert(parent)

    And you will end up with a new `ParentModel` and the two existing children
    will be re-assigned to the new parent. To copy them, use a sub-converter:

        class ChildConverter(AutoDjangoModelConverter):
            from_class = ChildModel
            to_class = ChildModel

        class DeepParentConverter(AutoDjangoModelConverter):
            from_class = dict
            to_class = ParentModel
            converter_copy_attrs = [
                ('children', ChildConverter),
            ]

        DeepParentConverter.convert(parent)

    This is tested in `test_converter_django_model.py`.
    """

    converter_options = {
        'pass_attrs_to_init': True,
        'django_model_atomic': False,
        'django_model_converter_save': True,
        'django_model_add_fields_to_copy_attrs': False,
    }

    @property
    def should_save(self):
        return (
            issubclass(self.to_class, Model)
            and self._resolved_converter_options['django_model_converter_save']
        )

    @property
    def should_add_fields_to_copy_attrs(self):
        return self._resolved_converter_options['django_model_add_fields_to_copy_attrs']

    @property
    def is_to_direction(self):
        # This controls how we deduce which fields to copy.
        #
        # If we are copying to a Model we use the target's fields.
        #
        # If we are not copying to a Model but are copying from a Model
        # we should use the source's fields.
        #
        # This can be overridden by subclasses who may wish to convert Model to
        # Model and use the source Model's fields.
        return issubclass(self.to_class, Model)

    def dynamic_copy_attrs(self):
        attrs = list(self.normalize_copy_attrs(super().dynamic_copy_attrs()))

        to_is_model = issubclass(self.to_class, Model)
        from_is_model = issubclass(self.from_class, Model)

        to_fields = {} if not to_is_model else _dict_of_model_fields(self.to_class)
        from_fields = {} if not from_is_model else _dict_of_model_fields(self.from_class)

        if self.is_to_direction:
            copy_fields = to_fields
            fname_to_copy_attr_ind_map = {
                to_attr: ind for ind, (to_attr, from_attr, opts) in enumerate(attrs)
            }
        else:
            copy_fields = from_fields
            fname_to_copy_attr_ind_map = {
                from_attr: ind
                for ind, (to_attr, from_attr, opts) in enumerate(attrs)
                if from_attr != NOS
            }

        for fname in copy_fields.keys():
            if fname in {'id', 'pk'}:
                # do not copy the id or pk by default, generally we are trying
                # to make a copy of the row, not update an existing one.
                continue

            to_attrs_set = {to_attr for (to_attr, _, _) in attrs}

            # ! this mutates attrs
            self._ensure_field_is_in_copy_attrs(
                fname, fname_to_copy_attr_ind_map, attrs, to_is_model, from_is_model, to_attrs_set
            )

        return attrs

    def instantiate(self, dct):
        inst = super().instantiate(dct)
        if inst is None or inst is _SENTRY:
            return inst
        # by default save immediately after instantiating so that reverse
        # relation operations will work
        if self.should_save:
            inst.save(force_insert=True)
        return inst

    def populate_instance(self, inst, params):
        if len(params) == 0:
            # nothing to do
            return inst
        inst = super().populate_instance(inst, params)
        if self.should_save:
            inst.save()
        return inst

    def instance_convert(self):
        if self._resolved_converter_options['django_model_atomic']:
            with atomic():
                return super().instance_convert()
        return super().instance_convert()

    # ----------------------------------------------------------------------------------------------
    # Private methods
    # ----------------------------------------------------------------------------------------------
    def _ensure_field_is_in_copy_attrs(
        self, fname, fname_to_copy_attr_ind_map, attrs, to_is_model, from_is_model, to_attrs_set
    ):
        # build the options for this field, using any current ones
        if fname not in fname_to_copy_attr_ind_map:
            if not self.should_add_fields_to_copy_attrs:
                # we've been told not to add fields that aren't there.
                return

            to_name = fname
            if to_name in to_attrs_set:
                # this attribute is being copied by a different instruction, so
                # we don't need to
                return

            # if this is a to-many don't add it automatically by default, it's
            # likely not what the caller wants, and if it is they can add it
            # explicitly.
            if from_is_model:
                from_field = _dict_of_model_fields(self.from_class).get(fname)
                if _field_is_to_many(from_field):
                    return

            if to_is_model:
                to_field = _dict_of_model_fields(self.to_class).get(to_name)
                if _field_is_to_many(to_field):
                    return

            opts = {}
            from_name = fname
            attrs.append((to_name, from_name, opts))
        else:
            to_name, from_name, opts = attrs[fname_to_copy_attr_ind_map[fname]]

        if to_is_model:
            # We need to handle one to many relations by adding them
            # only after we've initialized (so that our row exists when
            # we try to set the back-refrencing foreign key on the relation),
            # and we need to use the correct setter.
            to_field = _dict_of_model_fields(self.to_class).get(to_name)
            if isinstance(to_field, ManyToOneRel):
                opts.setdefault('initialization_attribute', False)
                if not isinstance(to_field, OneToOneRel):
                    opts.setdefault('setter', _set_many_to_one_field(to_field.get_accessor_name()))
                opts.setdefault('reverse_attr_name', to_field.remote_field.name)

            if isinstance(to_field, (ManyToManyField, ManyToManyRel)):
                opts.setdefault('setter', _set_many_to_one_field(to_name))
                opts.setdefault('initialization_attribute', False)

            if isinstance(to_field, FileField):
                opts.setdefault('setter', _set_file_field)
                opts.setdefault('initialization_attribute', False)

        if from_is_model:
            # Need to convert from one to many relation manager to an actual
            # iterable of model instances we can convert with.
            from_field = _dict_of_model_fields(self.from_class).get(from_name)
            if isinstance(from_field, ManyToOneRel):

                def many_to_one_getter(src, from_attr, opts):
                    return getattr(src, from_field.get_accessor_name()).all()

                opts.setdefault('getter', many_to_one_getter)


class AutoDjangoModelConverter(DjangoModelConverter):
    converter_options = {
        'django_model_add_fields_to_copy_attrs': True,
    }

# --------------------------------------------------------------------------------------------------
# Private helper functions
# --------------------------------------------------------------------------------------------------
def _set_file_field(inst, attr, val, opts):
    if isinstance(val, FieldFile):
        # can just set directly
        setattr(inst, attr, val)
        return

    if val is None:
        setattr(inst, attr, None)
        return

    if isinstance(val, (bytes, str)):
        extension = opts.get('file_extension', attr)

        if extension and not extension.startswith('.'):
            extension = f'.{extension}'

        getattr(inst, attr).save(f'{inst.id}{extension}', ContentFile(val))
        return

    raise NotImplementedError('DjangoModelConverter can only convert str or bytes to FileField')


def _set_many_to_one_field(attr_name):
    def _set_many_to_one_field_inner(inst, attr, val):
        getattr(inst, attr_name).set(val)

    return _set_many_to_one_field_inner


def _dict_of_model_fields(model):
    return {
        (f.get_accessor_name() if isinstance(f, ForeignObjectRel) else f.name): f
        for f in model._meta.get_fields()
    }


def _field_is_to_many(field):
    return isinstance(field, ManyToManyField) or isinstance(field, ForeignObjectRel)
