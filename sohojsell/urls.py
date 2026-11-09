from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


def healthz(request):
    """সার্ভার চালু আছে কিনা (Cloudflare চালু হওয়ার পর এটা দেখে ট্রাফিক পাঠায়)। ডাটাবেস ছোঁয় না।"""
    return HttpResponse('ok', content_type='text/plain')


urlpatterns = [
    path('healthz/', healthz, name='healthz'),
    path('admin/', admin.site.urls),
    path('', include('store.urls')),
    path('accounts/', include('accounts.urls')),
    path('accounts/', include('allauth.urls')),   # নতুন — Facebook OAuth URLs
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
