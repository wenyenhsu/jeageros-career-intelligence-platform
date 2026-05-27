import pytest
from apps.applications.services import record_status_transition


@pytest.mark.django_db
def test_record_status_transition(application, user):
    history = record_status_transition(application, 'SAVED', 'APPLIED', user=user)
    assert history.old_status == 'SAVED'
    assert history.new_status == 'APPLIED'
    assert history.changed_by == user
