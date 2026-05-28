import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(username='admin', password='pass12345', is_staff=True)


@pytest.fixture
def guest_user(db):
    return User.objects.create_user(username='guest', password='pass12345')


@pytest.mark.django_db
def test_user_list_redirects_anonymous(client):
    response = client.get(reverse('user-list'))
    assert response.status_code == 302
    assert '/accounts/login/' in response.url


@pytest.mark.django_db
def test_user_list_accessible_to_staff(client, staff_user):
    client.force_login(staff_user)
    response = client.get(reverse('user-list'))
    assert response.status_code == 200
    assert 'User management' in response.content.decode()


@pytest.mark.django_db
def test_staff_can_create_admin_user(client, staff_user):
    client.force_login(staff_user)
    response = client.post(
        reverse('user-create'),
        data={
            'username': 'newadmin',
            'email': 'admin@example.com',
            'first_name': 'New',
            'last_name': 'Admin',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'role': 'admin',
        },
    )
    assert response.status_code == 302
    user = User.objects.get(username='newadmin')
    assert user.is_staff is True
    assert user.is_superuser is True


@pytest.mark.django_db
def test_staff_cannot_delete_self(client, staff_user):
    client.force_login(staff_user)
    response = client.post(reverse('user-delete', args=[staff_user.pk]))
    assert response.status_code == 302
    assert User.objects.filter(pk=staff_user.pk).exists()
