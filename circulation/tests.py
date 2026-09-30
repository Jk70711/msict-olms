from django.test import TestCase, Client
from accounts.models import OLMSUser, UserSession
from catalog.models import Book, BookCopy, Category
from circulation.models import SoftcopyAccessLog
from django.urls import reverse

class SoftcopyTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = OLMSUser.objects.create_user(username='testmember', email='test@test.com', password='testpassword')
        self.user.role = 'member'
        self.user.is_active = True
        self.user.save()
        
        self.cat = Category.objects.create(name='Test Category', shelf_prefix='TC')
        self.book = Book.objects.create(title='Test Book', author='Test Author', category=self.cat)
        self.copy = BookCopy.objects.create(book=self.book, copy_type='softcopy', status='available')

        # Fix SingleSessionMiddleware redirect by creating a UserSession
        self.client.force_login(self.user)
        session = self.client.session
        session.save()
        UserSession.objects.create(user=self.user, session_id=session.session_key)

    def test_download_free(self):
        # Download free
        response = self.client.get(reverse('free_softcopy_download', args=[self.copy.id]))
        self.assertEqual(response.status_code, 302)
        
        self.assertNotEqual(response.url, '/login/')
