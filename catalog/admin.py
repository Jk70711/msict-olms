from django.contrib import admin
from .models import Category, Course, Book, BookCopy, BookCourse, ExternalLibrary, News, InventoryLog


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'shelf_prefix', 'books_count')
    search_fields = ('name',)
    list_per_page = 30

    def books_count(self, obj):
        return obj.books.count()
    books_count.short_description = 'Books'


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('course_name', 'duration')
    search_fields = ('course_name',)


class BookCopyInline(admin.TabularInline):
    model = BookCopy
    extra = 1
    fields = ('copy_type', 'access_type', 'accession_no', 'status', 'shelf_location', 'barcode')
    show_change_link = True


class BookCourseInline(admin.TabularInline):
    model = BookCourse
    extra = 1


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'isbn', 'category', 'year', 'copies_count', 'show_in_carousel', 'created_at')
    list_filter = ('category', 'show_in_carousel', 'year')
    search_fields = ('title', 'author', 'isbn', 'publisher')
    inlines = [BookCopyInline, BookCourseInline]
    list_per_page = 25
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    actions = ['toggle_carousel']

    def copies_count(self, obj):
        return obj.copies.count()
    copies_count.short_description = 'Copies'

    def toggle_carousel(self, request, queryset):
        for book in queryset:
            book.show_in_carousel = not book.show_in_carousel
            book.save()
        self.message_user(request, "Carousel status toggled.")
    toggle_carousel.short_description = "Toggle carousel display"


@admin.register(BookCopy)
class BookCopyAdmin(admin.ModelAdmin):
    list_display = ('book', 'copy_type', 'access_type', 'accession_no', 'status', 'shelf_location')
    list_filter = ('copy_type', 'access_type', 'status')
    search_fields = ('accession_no', 'barcode', 'book__title', 'book__author')
    list_per_page = 30
    actions = ['mark_available', 'mark_withdrawn']

    def mark_available(self, request, queryset):
        updated = queryset.update(status='available')
        self.message_user(request, f"{updated} copy/copies marked available.")
    mark_available.short_description = "Mark selected copies as Available"

    def mark_withdrawn(self, request, queryset):
        updated = queryset.update(status='withdrawn')
        self.message_user(request, f"{updated} copy/copies marked withdrawn.")
    mark_withdrawn.short_description = "Mark selected copies as Withdrawn"


@admin.register(ExternalLibrary)
class ExternalLibraryAdmin(admin.ModelAdmin):
    list_display = ('name', 'base_url', 'lib_type', 'is_active')
    list_filter = ('lib_type', 'is_active')
    actions = ['activate', 'deactivate']

    def activate(self, request, queryset):
        queryset.update(is_active=True)
    activate.short_description = "Activate selected libraries"

    def deactivate(self, request, queryset):
        queryset.update(is_active=False)
    deactivate.short_description = "Deactivate selected libraries"


@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ('title', 'is_active', 'created_at', 'expires_at')
    list_filter = ('is_active',)
    search_fields = ('title',)


@admin.register(InventoryLog)
class InventoryLogAdmin(admin.ModelAdmin):
    list_display = ('copy', 'action', 'performed_by', 'timestamp')
    list_filter = ('action',)
    search_fields = ('copy__book__title', 'performed_by__username')
    readonly_fields = ('timestamp',)
    list_per_page = 50
    date_hierarchy = 'timestamp'
    ordering = ('-timestamp',)

    def has_add_permission(self, request):
        return False
