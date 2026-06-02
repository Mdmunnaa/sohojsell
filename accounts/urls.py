from django.urls import path
from . import views

urlpatterns = [
    path('signup/', views.signup, name='signup'),  # এটা আপনার আগে থেকেই ছিল

    # এই নতুন দুইটা লাইন অ্যাড করুন
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
]
