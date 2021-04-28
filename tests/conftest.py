import shutil

import pytest


@pytest.fixture(autouse=True)
def clean_up_uploads():
    yield
    shutil.rmtree('tests-django-app-files', ignore_errors=True)
