# ============================================================
# catalog/urls.py — URL za Vitabu, Nakala, Rafu, na Maudhui
# Zinahitaji kuingia (librarian au admin) isipokuwa ile ya kusoma PDF
# ============================================================

from django.urls import path
from . import views

urlpatterns = [
    # ── Dashboard ya Mtunzaji ──────────────────────────────────
    path('librarian-dashboard/', views.librarian_dashboard_view, name='librarian_dashboard'),  # Dashboard ya mtunzaji

    # ── Vitabu ────────────────────────────────────────────
    path('books/', views.book_list_view, name='book_list'),                                    # Orodha ya vitabu
    path('books/create/', views.book_create_view, name='book_create'),                         # Unda kitabu kipya
    path('books/<int:book_id>/', views.book_detail_view, name='book_detail'),                  # Maelezo ya kitabu
    path('books/<int:book_id>/edit/', views.book_edit_view, name='book_edit'),                 # Hariri kitabu
    path('books/<int:book_id>/delete/', views.book_delete_view, name='book_delete'),           # Futa kitabu
    path('books/<int:book_id>/add-copy/', views.copy_create_view, name='copy_create'),         # Ongeza nakala kwa kitabu
    path('search/', views.book_search_ajax, name='book_search_ajax'),                          # AJAX search endpoint

    # ── Nakala za Vitabu ─────────────────────────────────────
    path('copies/', views.copy_list_view, name='copy_list'),                                   # Orodha ya nakala zote
    path('copies/add/', views.copy_add_standalone_view, name='copy_add'),                      # Ongeza nakala (njia mbadala)
    path('copies/<int:copy_id>/edit/', views.copy_edit_view, name='copy_edit'),                # Hariri nakala
    path('copies/<int:copy_id>/delete/', views.copy_delete_view, name='copy_delete'),          # Futa nakala
    path('copies/<int:copy_id>/mark-lost/', views.copy_mark_lost_view, name='copy_mark_lost'), # Taja nakala kama imepotea
    path('copies/<int:copy_id>/read/', views.serve_softcopy_view, name='serve_softcopy'),      # Soma PDF online
    path('copies/<int:copy_id>/download/', views.free_softcopy_download_view, name='free_softcopy_download'),  # Pakua PDF bure

    # ── Kozi na Makategoria ────────────────────────────────
    path('courses/', views.course_list_view, name='course_list'),                              # Orodha ya kozi
    path('courses/create/', views.course_create_view, name='course_create'),                   # Unda kozi mpya
    path('courses/<int:course_id>/edit/', views.course_edit_view, name='course_edit'),         # Hariri kozi
    path('courses/<int:course_id>/delete/', views.course_delete_view, name='course_delete'),   # Futa kozi
    path('categories/', views.category_list_view, name='category_list'),                       # Orodha ya makategoria
    path('categories/create/', views.category_create_view, name='category_create'),            # Unda kategoria mpya

    # ── Rafu ──────────────────────────────────────────────
    path('shelf-locations/', views.shelf_location_view, name='shelf_location'),                # Orodha ya mahali pa rafu
    path('shelf-locations/<int:shelf_id>/', views.shelf_detail_view, name='shelf_detail'),     # Maelezo ya rafu moja
    path('shelves/', views.shelf_list_all_view, name='shelf_list_all'),                        # Orodha kamili ya rafu
    path('shelves/create/', views.shelf_create_view, name='shelf_create'),                     # Unda rafu mpya
    path('shelves/<int:shelf_id>/edit/', views.shelf_edit_view, name='shelf_edit'),            # Hariri rafu
    path('shelves/<int:shelf_id>/delete/', views.shelf_delete_view, name='shelf_delete'),      # Futa rafu

    # ── API za Msaada ───────────────────────────────────────
    path('api/shelves-by-category/<int:category_id>/', views.shelves_by_category_api, name='shelves_by_category_api'),  # Rafu za kategoria (AJAX)
    path('api/next-accession/', views.next_accession_api, name='next_accession_api'),          # Nambari inayofuata ya accession
    path('api/federated-search/', views.federated_proxy_view, name='federated_proxy'),         # Tafuta maktaba za nje

    # ── Maktaba za Nje, Carousel, na Picha ──────────────────
    path('external-libraries/', views.external_library_list_view, name='external_library_list'),          # Maktaba za nje
    path('external-libraries/create/', views.external_library_create_view, name='external_library_create'), # Ongeza maktaba ya nje
    path('carousel/', views.carousel_manage_view, name='carousel_manage'),                     # Simamia carousel
    path('media-slides/', views.media_slide_list_view, name='media_slide_list'),               # Orodha ya picha/slides
    path('media-slides/create/', views.media_slide_create_view, name='media_slide_create'),    # Ongeza slide mpya
    path('media-slides/<int:slide_id>/edit/', views.media_slide_edit_view, name='media_slide_edit'),    # Hariri slide
    path('media-slides/<int:slide_id>/delete/', views.media_slide_delete_view, name='media_slide_delete'), # Futa slide

    # ── Habari na Matangazo ─────────────────────────────────
    path('news/', views.news_list_view, name='news_list'),                                     # Orodha ya habari
    path('news/create/', views.news_create_view, name='news_create'),                          # Unda habari mpya
    path('news/<int:news_id>/edit/', views.news_edit_view, name='news_edit'),                  # Hariri habari
    path('news/<int:news_id>/delete/', views.news_delete_view, name='news_delete'),            # Futa habari
    path('news/<int:news_id>/toggle/', views.news_toggle_view, name='news_toggle'),            # Washa/zima habari
]
