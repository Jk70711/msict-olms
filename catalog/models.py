# ============================================================
# catalog/models.py
# Mifano ya data kwa vitabu, nakala, rafu, makategoria,
# habari, picha za carousel, na maktaba za nje
# ============================================================

from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from accounts.models import OLMSUser


# ----------------------------------------------------------------------
# Model ya Kategoria — Aina/Somo la vitabu
# Inaweza kuwa na kategoria mama (parent)
# Kila kategoria inapewa herufi ya rafu (A, B, C...) otomatiki
# ----------------------------------------------------------------------
class Category(models.Model):
    name = models.CharField(max_length=100)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='subcategories')
    shelf_prefix = models.CharField(max_length=3, unique=True, blank=True, help_text='Auto-assigned shelf letter prefix (A, B, C...)')

    class Meta:
        db_table = 'categories'
        verbose_name_plural = 'Categories'

    def __str__(self):
        if self.parent:
            return f"{self.parent.name} > {self.name}"
        return self.name

    def get_full_path(self):
        if self.parent:
            return f"{self.parent.get_full_path()} > {self.name}"
        return self.name

    def save(self, *args, **kwargs):
        if not self.shelf_prefix:
            used = set(Category.objects.exclude(pk=self.pk).values_list('shelf_prefix', flat=True))
            for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
                if letter not in used:
                    self.shelf_prefix = letter
                    break
        super().save(*args, **kwargs)

    def get_shelves(self):
        return self.shelves.order_by('shelf_number')


# ----------------------------------------------------------------------
# Model ya Kozi — Kozi za shule
# Zinaunganishwa na Category
# Vitabu vinaweza kuwa vya kozi moja au zaidi
# ----------------------------------------------------------------------
class Course(models.Model):
    course_name = models.CharField(max_length=200)
    duration = models.CharField(max_length=50, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='courses', help_text='Optional: Assign as subcategory under a main category')

    class Meta:
        db_table = 'courses'

    def __str__(self):
        return self.course_name


# ----------------------------------------------------------------------
# Model ya Kitabu — Taarifa za kitabu
# Jina, mwandishi, ISBN, picha ya jalada n.k.
# Kitabu kimoja kinaweza kuwa na nakala nyingi (BookCopy)
# ----------------------------------------------------------------------
class Book(models.Model):
    isbn = models.CharField(max_length=13, unique=True, null=True, blank=True)
    title = models.CharField(max_length=500)
    author = models.CharField(max_length=200, blank=True)
    publisher = models.CharField(max_length=200, blank=True)
    year = models.IntegerField(null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='books')
    summary = models.TextField(blank=True)
    cover_image = models.ImageField(upload_to='book_covers/', null=True, blank=True)
    marc_xml = models.TextField(blank=True)
    show_in_carousel = models.BooleanField(default=False)
    lost_fine = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # Fine if copy is lost
    courses = models.ManyToManyField(Course, through='BookCourse', blank=True, related_name='books')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'books'
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def available_hardcopy_count(self):
        return self.copies.filter(copy_type='hardcopy', status='available').count()

    def has_free_softcopy(self):
        return self.copies.filter(copy_type='softcopy', access_type='free', status='available').exists()

    def has_special_softcopy(self):
        return self.copies.filter(copy_type='softcopy', access_type='borrow').exists()

    def total_hardcopies(self):
        return self.copies.filter(copy_type='hardcopy').count()

    def free_softcopy_count(self):
        return self.copies.filter(copy_type='softcopy', access_type='free').count()

    def special_softcopy_count(self):
        return self.copies.filter(copy_type='softcopy', access_type='borrow').count()

    def available_special_softcopy_count(self):
        return self.copies.filter(copy_type='softcopy', access_type='borrow', status='available').count()

    @property
    def book_type(self):
        """Derived type from copies: hardcopy / softcopy / both."""
        has_hard = self.copies.filter(copy_type='hardcopy').exists()
        has_soft = self.copies.filter(copy_type='softcopy').exists()
        if has_hard and has_soft:
            return 'both'
        if has_soft:
            return 'softcopy'
        return 'hardcopy'

    @property
    def book_type_display(self):
        t = self.book_type
        return {'both': 'Both (Hard + Soft)', 'softcopy': 'Softcopy', 'hardcopy': 'Hardcopy'}.get(t, t)


# ----------------------------------------------------------------------
# Model ya BookCourse — Uhusiano wa vitabu na kozi (many-to-many)
# ----------------------------------------------------------------------
class BookCourse(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)

    class Meta:
        db_table = 'book_courses'
        unique_together = ('book', 'course')


# ----------------------------------------------------------------------
# Model ya Nakala ya Kitabu — Nakala halisi ya kitabu
# Inaweza kuwa hardcopy (kimwili) au softcopy (PDF)
# Kila nakala ina nambari ya accession ya kipekee (e.g. MSICT/000001)
# ----------------------------------------------------------------------
class BookCopy(models.Model):
    COPY_TYPE_CHOICES = [('hardcopy', 'Hardcopy'), ('softcopy', 'Softcopy')]
    ACCESS_TYPE_CHOICES = [('borrow', 'Special Soft Copy'), ('free', 'Free Soft Copy')]
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('borrowed', 'Borrowed'),
        ('reserved', 'Reserved'),
        ('lost', 'Lost'),
    ]

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='copies')
    copy_type = models.CharField(max_length=10, choices=COPY_TYPE_CHOICES)
    access_type = models.CharField(max_length=10, choices=ACCESS_TYPE_CHOICES, null=True, blank=True)
    accession_no = models.CharField(max_length=50, unique=True)
    file_path = models.FileField(upload_to='ebooks/', null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='available')
    shelf_location = models.CharField(max_length=50, blank=True)
    barcode = models.CharField(max_length=50, unique=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'book_copies'
        verbose_name = 'Book Copy'
        verbose_name_plural = 'Book Copies'

    def __str__(self):
        return f"{self.book.title} [{self.accession_no}] - {self.copy_type}"

    def get_access_display(self):
        """Human-readable access label (used in all templates)."""
        if self.copy_type == 'hardcopy':
            return 'Borrowing'
        if self.access_type == 'free':
            return 'Free Download'
        if self.access_type == 'borrow':
            return 'Special Borrow'
        return '—'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.copy_type == 'hardcopy' and self.access_type:
            raise ValidationError("Hardcopy cannot have access_type set.")
        if self.copy_type == 'softcopy' and not self.access_type:
            raise ValidationError("Softcopy must have access_type set.")

    @classmethod
    def get_next_accession_number(cls, offset=0, for_softcopy=False):
        """Return the next accession number.
        Hardcopy: MSICT/000001 format (reuses tombstoned numbers).
        Softcopy: SOFT/000001 format (separate counter, never tombstoned).
        """
        if for_softcopy:
            last_num = 0
            for acc in cls.objects.filter(copy_type='softcopy').values_list('accession_no', flat=True):
                if acc and acc.startswith('SOFT/'):
                    try:
                        n = int(acc[5:])
                        if n > last_num:
                            last_num = n
                    except ValueError:
                        pass
            return f"SOFT/{last_num + 1:06d}"
        # Hardcopy: reuse freed (tombstoned) numbers first
        if offset == 0:
            freed = DeletedAccessionNumber.objects.order_by('number').first()
            if freed:
                acc = freed.accession_no
                freed.delete()
                return acc
        last_num = 0
        for acc in cls.objects.values_list('accession_no', flat=True):
            if not acc:
                continue
            try:
                if acc.startswith('MSICT/'):
                    n = int(acc[6:])
                elif acc.startswith('ACC-'):
                    n = int(acc[4:])
                else:
                    continue
                if n > last_num:
                    last_num = n
            except ValueError:
                pass
        return f"MSICT/{last_num + offset + 1:06d}"

    @property
    def display_id(self):
        """Show accession number for hardcopy, 'Link' for softcopy."""
        return self.accession_no if self.copy_type == 'hardcopy' else 'Link'

    def save(self, *args, **kwargs):
        if self.copy_type == 'hardcopy':
            self.access_type = None
        if not self.barcode:
            self.barcode = self.accession_no
        super().save(*args, **kwargs)


# ----------------------------------------------------------------------
# Model ya DeletedAccessionNumber — Nambari za accession zilizofutwa
# Inafuatilia nambari za accession zilizofutwa ili kutumika tena
# ----------------------------------------------------------------------
class DeletedAccessionNumber(models.Model):
    """Tombstone table: tracks permanently deleted copy accession numbers for reuse."""
    accession_no = models.CharField(max_length=50, unique=True)
    number       = models.PositiveIntegerField(default=0, db_index=True)
    deleted_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'deleted_accession_numbers'
        ordering = ['number']

    def __str__(self):
        return self.accession_no


# ----------------------------------------------------------------------
# Signal — Rekodi nambari ya accession wakati nakala inafutwa
# ----------------------------------------------------------------------
@receiver(post_delete, sender='catalog.BookCopy')
def tombstone_accession_on_delete(sender, instance, **kwargs):
    """Wakati nakala inafutwa, rekodi nambari ya accession ili kutumika tena.
    Nambari za SOFT/ hazirekodiwa — ni za kidijitali na hazihitaji kutumika tena.
    """
    acc = instance.accession_no
    if not acc or acc.startswith('SOFT/'):
        return
    number = 0
    try:
        if acc.startswith('MSICT/'):
            number = int(acc[6:])
        elif acc.startswith('ACC-'):
            number = int(acc[4:])
    except ValueError:
        pass
    if number > 0:
        DeletedAccessionNumber.objects.get_or_create(
            accession_no=acc,
            defaults={'number': number},
        )


# ----------------------------------------------------------------------
# Model ya Rafu — Rafu ya kimwili kwenye maktaba
# Kila rafu ina nambari ya kipekee kama SHELF-A1, SHELF-B2 n.k.
# ----------------------------------------------------------------------
class Shelf(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='shelves')
    shelf_number = models.PositiveIntegerField(default=1)
    name = models.CharField(max_length=100, blank=True, help_text='Optional descriptive name')
    capacity = models.PositiveIntegerField(default=50, help_text='Max number of books')
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'shelves'
        unique_together = ('category', 'shelf_number')
        ordering = ['category__shelf_prefix', 'shelf_number']

    def __str__(self):
        return self.shelf_code

    @property
    def shelf_code(self):
        prefix = self.category.shelf_prefix or '?'
        return f"SHELF-{prefix}{self.shelf_number}"

    def save(self, *args, **kwargs):
        if not self.pk and not self.shelf_number:
            last = Shelf.objects.filter(category=self.category).order_by('-shelf_number').first()
            self.shelf_number = (last.shelf_number + 1) if last else 1
        super().save(*args, **kwargs)

    def book_count(self):
        return BookCopy.objects.filter(shelf_location=self.shelf_code, copy_type='hardcopy').count()


# ----------------------------------------------------------------------
# Model ya InventoryLog — Historia ya harakati za nakala
# Inarekodi: imongezwa, imepotea, imehaririwa
# ----------------------------------------------------------------------
class InventoryLog(models.Model):
    copy = models.ForeignKey(BookCopy, on_delete=models.SET_NULL, null=True, related_name='inventory_logs')
    action = models.CharField(max_length=50)
    performed_by = models.ForeignKey(OLMSUser, on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'inventory_logs'
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.action} on {self.copy} by {self.performed_by}"


# ----------------------------------------------------------------------
# Model ya ExternalLibrary — Maktaba za nje (federated search)
# Inatumika kwa kutafuta vitabu kutoka maktaba nyingine
# ----------------------------------------------------------------------
class ExternalLibrary(models.Model):
    LIB_TYPE_CHOICES = [('opac', 'OPAC'), ('z3950', 'Z39.50'), ('api', 'API')]
    name = models.CharField(max_length=200)
    base_url = models.URLField(max_length=500)
    search_param = models.CharField(max_length=100, default='q')
    is_active = models.BooleanField(default=True)
    lib_type = models.CharField(max_length=20, choices=LIB_TYPE_CHOICES, default='opac')

    class Meta:
        db_table = 'external_libraries'
        verbose_name = 'External Library'
        verbose_name_plural = 'External Libraries'

    def __str__(self):
        return self.name

    def build_search_url(self, query):
        from urllib.parse import urlencode
        return f"{self.base_url}?{urlencode({self.search_param: query})}"


# ----------------------------------------------------------------------
# Model ya News — Habari, matangazo, matukio
# Yanaonekana kwenye ukurasa wa nyumbani
# ----------------------------------------------------------------------
class News(models.Model):
    TYPE_CHOICES = [
        ('news',         'News'),
        ('announcement', 'Announcement'),
        ('event',        'Event'),
        ('advertisement','Advertisement'),
    ]

    title       = models.CharField(max_length=255)
    content     = models.TextField()
    news_type   = models.CharField(max_length=20, choices=TYPE_CHOICES, default='news')
    image       = models.ImageField(upload_to='news/', null=True, blank=True, help_text='Cover image (JPG/PNG)')
    video_url   = models.URLField(max_length=500, blank=True, help_text='YouTube/Vimeo embed URL (e.g. https://www.youtube.com/embed/xxx)')
    link_url    = models.URLField(max_length=500, blank=True, help_text='Optional external link (opens in new tab)')
    attachment  = models.FileField(upload_to='news/attachments/', null=True, blank=True, help_text='PDF or document attachment')
    posted_by   = models.ForeignKey(OLMSUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='news_posts')
    is_active   = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False, help_text='Pin to top of news feed')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
    expires_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'news'
        verbose_name_plural = 'News'
        ordering = ['-is_featured', '-created_at']

    def __str__(self):
        return self.title

    def is_expired(self):
        from django.utils import timezone
        return self.expires_at and timezone.now() > self.expires_at

    def embed_video_url(self):
        """Convert any YouTube watch URL to embed format."""
        import re
        if not self.video_url:
            return ''
        # already an embed URL
        if 'embed' in self.video_url:
            return self.video_url
        # youtube.com/watch?v=ID
        m = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})', self.video_url)
        if m:
            return f'https://www.youtube.com/embed/{m.group(1)}'
        # vimeo.com/ID
        m = re.search(r'vimeo\.com/(\d+)', self.video_url)
        if m:
            return f'https://player.vimeo.com/video/{m.group(1)}'
        return self.video_url


# ----------------------------------------------------------------------
# Model ya MediaSlide — Picha za carousel kwenye ukurasa wa nyumbani
# Pia inatumika kwa logo ya mfumo (slide_type='logo')
# ----------------------------------------------------------------------
class MediaSlide(models.Model):
    SLIDE_TYPE_CHOICES = [
        ('carousel', 'Homepage Carousel'),
        ('advertisement', 'Advertisement'),
        ('news', 'News Banner'),
        ('announcement', 'Announcement'),
        ('logo', 'System Logo'),
        ('home_bg', 'Home Page Background'),
    ]
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='media_slides/', help_text='Recommended: 1200x400px for carousel')
    slide_type = models.CharField(max_length=20, choices=SLIDE_TYPE_CHOICES, default='carousel')
    bg_color = models.CharField(max_length=20, blank=True, default='#001a33', help_text='Background color for carousel (hex code, e.g., #001a33)')
    link_url = models.URLField(max_length=500, blank=True, help_text='Optional link when clicked')
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0, help_text='Lower numbers display first')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True, help_text='Leave blank for permanent display')
    created_by = models.ForeignKey(OLMSUser, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        db_table = 'media_slides'
        ordering = ['display_order', '-created_at']
        verbose_name = 'Media Slide'
        verbose_name_plural = 'Media Slides'

    def __str__(self):
        return f"{self.title} ({self.slide_type})"

    def save(self, *args, **kwargs):
        # Ensure only one active logo exists
        if self.slide_type == 'logo' and self.is_active:
            MediaSlide.objects.filter(slide_type='logo', is_active=True).exclude(pk=self.pk).update(is_active=False)
        # Ensure only one active home background exists
        if self.slide_type == 'home_bg' and self.is_active:
            MediaSlide.objects.filter(slide_type='home_bg', is_active=True).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    @classmethod
    def get_active_logo(cls):
        """Get the currently active system logo"""
        return cls.objects.filter(slide_type='logo', is_active=True).first()

    @classmethod
    def get_active_home_bg(cls):
        """Get the currently active home page background/watermark image"""
        return cls.objects.filter(slide_type='home_bg', is_active=True).first()


# ----------------------------------------------------------------------
# Model ya Footer — Maudhui ya footer yanayoweza kuhaririwa
# Ina: jina la shule, anwani, simu, barua pepe, viungo vya kijamii
# ----------------------------------------------------------------------
class Footer(models.Model):
    """Maudhui ya footer yanayoweza kuhaririwa kwa tovuti"""
    school_name = models.CharField(max_length=255, default='MSICT Library')
    address = models.TextField(blank=True, help_text='Physical address')
    phone = models.CharField(max_length=50, blank=True, help_text='Contact phone number')
    email = models.EmailField(blank=True, help_text='Contact email')
    location = models.CharField(max_length=255, blank=True, help_text='Location/city')
    copyright_text = models.CharField(max_length=255, default='© 2024 MSICT. All rights reserved.')
    faq_link = models.URLField(max_length=500, blank=True, help_text='FAQ page URL')
    social_facebook = models.URLField(max_length=500, blank=True)
    social_twitter = models.URLField(max_length=500, blank=True)
    social_linkedin = models.URLField(max_length=500, blank=True)
    social_instagram = models.URLField(max_length=500, blank=True)
    additional_links = models.TextField(blank=True, help_text='Additional footer links (one per line: Label|URL)')
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(OLMSUser, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        db_table = 'footer'
        verbose_name = 'Footer Configuration'
        verbose_name_plural = 'Footer Configurations'

    def __str__(self):
        return f"Footer - {self.school_name}"

    @classmethod
    def get_active_footer(cls):
        """Get the currently active footer configuration"""
        return cls.objects.filter(is_active=True).first()
