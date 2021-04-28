from django.db.models import FileField, ForeignKey, Model, TextField, CASCADE


class DjangoModelConverterTestModel(Model):
    a_file = FileField(null=True, blank=True, upload_to='tests-django-app-files')
    parent = ForeignKey('DMCTestParentModel', on_delete=CASCADE, related_name='children', null=True)
    child_text = TextField(blank=True, default='')


class DMCTestParentModel(Model):
    parent_text = TextField(blank=True, default='')

