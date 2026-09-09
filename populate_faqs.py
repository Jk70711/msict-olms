import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'OLMS.settings')
django.setup()

from public.models import FAQ

def populate_faqs():
    print("Clearing existing FAQs...")
    FAQ.objects.all().delete()

    faqs = [
        {
            "question": "How do I borrow a book from the MSICT Library?",
            "answer": "To borrow a book, you must be a registered member. Browse our catalog, select a book, and click the 'Borrow' button. You can then pick up the physical copy from the library desk.",
            "order": 1,
        },
        {
            "question": "How do I start a guest session?",
            "answer": "Walk-in guests can access our digital resources by visiting the 'Guest Session' page and registering with their basic details. A temporary receipt with credentials will be generated after paying the required session fee.",
            "order": 2,
        },
        {
            "question": "What happens if I return a book late?",
            "answer": "Late returns may be subject to overdue fines according to library policy. Please check your dashboard for due dates and renew your books if needed.",
            "order": 3,
        },
        {
            "question": "How can I access external digital resources?",
            "answer": "Registered members and active guests can access external databases by logging in and using the provided links in our catalog, such as the EBSCOhost search portal.",
            "order": 4,
        },
    ]

    for faq_data in faqs:
        FAQ.objects.create(
            question=faq_data['question'],
            answer=faq_data['answer'],
            order=faq_data['order'],
            is_active=True
        )
        print(f"Created FAQ: {faq_data['question']}")

    print("Successfully populated FAQs.")

if __name__ == '__main__':
    populate_faqs()
