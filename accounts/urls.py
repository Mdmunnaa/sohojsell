from django.urls import path
from . import views

urlpatterns = [
    path('signup/', views.signup, name='signup'),
    path('check-subdomain/', views.check_subdomain, name='check_subdomain'),
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
    path('forgot/', views.password_forgot, name='password_forgot'),
    path('forgot/code/', views.password_reset_code, name='password_reset_code'),
    path('my-password/', views.password_change, name='password_change'),
]
