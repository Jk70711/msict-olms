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
    path('books/bulk-import/', views.bulk_import_books_view, name='bulk_import_books'),         # Ingiza vitabu wingi
    path('books/bulk-import/template/', views.bulk_import_books_template_view, name='bulk_import_template'),  # Pakua templeti ya CSV
    path('books/new-arrival-broadcast/', views.new_arrival_broadcast_view, name='new_arrival_broadcast'),  # Tangaza vitabu vipya
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
    path('copies/<int:copy_id>/mark-lost/', views.copy_mark_lost_view, name='copy_mark_lost'), # Taji nakala kama imepotea
    path('copies/<int:copy_id>/read/', views.serve_softcopy_view, name='serve_softcopy'),                          # Soma PDF online
    path('copies/access/<uuid:token>/', views.softcopy_access_link_view, name='softcopy_access'),                    # Tokenized access link
    path('copies/<int:copy_id>/pdf-data/', views.special_pdf_data_view, name='special_pdf_data'),                 # Raw PDF bytes (viewer only)
    path('copies/<int:copy_id>/free-data/', views.free_softcopy_data_view, name='free_softcopy_data'),              # Raw bytes for free softcopy viewer
    path('copies/<int:copy_id>/download/', views.free_softcopy_download_view, name='free_softcopy_download'),     # Pakua PDF bure

    # ── Kozi na Makategoria ────────────────────────────────
    path('courses/', views.course_list_view, name='course_list'),                              # Orodha ya kozi
    path('courses/create/', views.course_create_view, name='course_create'),                   # Unda kozi mpya
    path('courses/<int:course_id>/edit/', views.course_edit_view, name='course_edit'),         # Hariri kozi
    path('courses/<int:course_id>/delete/', views.course_delete_view, name='course_delete'),   # Futa kozi
    path('categories/', views.category_list_view, name='category_list'),                       # Orodha ya makategoria
    path('categories/create/', views.category_create_view, name='category_create'),            # Unda kategoria mpya
    path('categories/<int:category_id>/edit/', views.category_edit_view, name='category_edit'), # Hariri kategoria
    path('categories/<int:category_id>/delete/', views.category_delete_view, name='category_delete'), # Futa kategoria

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
    path('footer/edit/', views.footer_edit_view, name='footer_edit'),                          # Hariri maelezo ya footer

    # ── Login Page Content Management ────────────────────────
    path('login-content/', views.login_content_list_view, name='login_content_list'),
    path('login-content/<int:section_id>/edit/', views.login_content_edit_view, name='login_content_edit'),
    path('login-content/<int:section_id>/toggle/', views.login_content_toggle_view, name='login_content_toggle'),
    path('login-slideshow/create/', views.login_slideshow_create_view, name='login_slideshow_create'),
    path('login-slideshow/<int:slide_id>/delete/', views.login_slideshow_delete_view, name='login_slideshow_delete'),
]
