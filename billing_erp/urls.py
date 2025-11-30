from django.contrib import admin
from django.urls import path, include
from bills import views

urlpatterns = [
    path('admin/', admin.site.urls),

    # 👇 include all billing routes (login, home, etc.)
    path('', include('bills.urls')),
        path('', views.index, name='index'),
]
