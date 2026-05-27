from apps.reminders.tasks import generate_followup_reminders


def test_generate_followup_reminders():
    result = generate_followup_reminders()
    assert result['status'] == 'ok'
