from django.urls import include, path

from .views import UserCreateView, UserDeleteView, UserListView, UserUpdateView

urlpatterns = [
    path('', include('django.contrib.auth.urls')),
    path('users/', UserListView.as_view(), name='user-list'),
    path('users/new/', UserCreateView.as_view(), name='user-create'),
    path('users/<int:pk>/edit/', UserUpdateView.as_view(), name='user-update'),
    path('users/<int:pk>/delete/', UserDeleteView.as_view(), name='user-delete'),
]
