# ============================================================
# public/urls.py — URL za Kurasa za Umma
# Hizi zinaonekana bila kuingia — mtu yeyote anaweza kuzifikia
# ============================================================

from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),                                              # / — Ukurasa wa nyumbani
    path('catalog/', views.catalog_search_view, name='catalog_search'),                  # /catalog/ — Tafuta vitabu
    path('catalog/autocomplete/', views.catalog_autocomplete_api, name='catalog_autocomplete'),  # API ya utambuzi wa haraka
    path('books/<int:book_id>/', views.book_detail_public_view, name='book_detail_public'),      # /books/5/ — Maelezo ya kitabu
    path('api/book/<int:book_id>/modal/', views.book_modal_data_view, name='book_modal_data'),   # API ya modal popup
]
