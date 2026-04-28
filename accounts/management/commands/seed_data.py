from django.core.management.base import BaseCommand
from django.utils import timezone
from accounts.models import OLMSUser, SystemPreference
from catalog.models import Category, Course, Book, BookCopy, ExternalLibrary, News
from acquisitions.models import Vendor


class Command(BaseCommand):
    help = 'Seed initial data: categories, courses, books, copies, members, librarian, news, external libraries, vendors.'

    def handle(self, *args, **options):
        self._seed_categories()
        self._seed_courses()
        self._seed_system_preferences()
        self._seed_external_libraries()
        self._seed_news()
        self._seed_vendors()
        self._seed_books()
        self._seed_members()
        self.stdout.write(self.style.SUCCESS('[seed_data] All initial data seeded successfully.'))

    # ── CATEGORIES ──────────────────────────────────────────────────────────

    def _seed_categories(self):
        cats = [
            'Science & Technology', 'Military & Defence', 'Engineering',
            'Information Technology', 'Mathematics', 'Language & Literature',
            'Social Sciences', 'History & Geography', 'Medical & Health',
            'Law & Governance', 'Business & Management', 'Leadership',
        ]
        created = 0
        for name in cats:
            _, c = Category.objects.get_or_create(name=name)
            if c:
                created += 1
        self.stdout.write(f'  Categories: {created} created.')

    # ── COURSES ──────────────────────────────────────────────────────────────

    def _seed_courses(self):
        courses = [
            ('Bachelor of Information Technology', '3 years'),
            ('Bachelor of Computer Science', '3 years'),
            ('Diploma in ICT', '2 years'),
            ('Certificate in ICT', '1 year'),
            ('Military Leadership Course', '6 months'),
            ('Advanced ICT Officers Course', '1 year'),
            ('Junior Command and Staff Course', '1 year'),
            ('Senior Command and Staff Course', '2 years'),
        ]
        created = 0
        for name, duration in courses:
            _, c = Course.objects.get_or_create(course_name=name, defaults={'duration': duration})
            if c:
                created += 1
        self.stdout.write(f'  Courses: {created} created.')

    # ── SYSTEM PREFERENCES ───────────────────────────────────────────────────

    def _seed_system_preferences(self):
        prefs = [
            ('LOAN_PERIOD_DAYS', '7', 'Default loan period in days for hardcopies'),
            ('SOFTCOPY_LOAN_PERIOD_DAYS', '3', 'Loan period in days for special softcopies'),
            ('MAX_RENEWALS', '2', 'Maximum number of renewals per transaction'),
            ('MAX_COPIES_PER_BORROW', '3', 'Maximum simultaneous borrows per member'),
            ('FINE_PER_DAY', '500', 'Fine amount per overdue day in TZS'),
            ('OTP_VALIDITY_MINUTES', '10', 'OTP validity period in minutes'),
            ('MAX_LOGIN_ATTEMPTS', '5', 'Max failed login attempts before account lockout'),
        ]
        created = 0
        for key, value, desc in prefs:
            _, c = SystemPreference.objects.get_or_create(
                key=key, defaults={'value': value, 'description': desc}
            )
            if c:
                created += 1
        self.stdout.write(f'  System preferences: {created} created.')

    # ── EXTERNAL LIBRARIES ───────────────────────────────────────────────────

    def _seed_external_libraries(self):
        libs = [
            ('Internet Archive', 'https://archive.org/search', 'query', 'opac'),
            ('Open Library', 'https://openlibrary.org/search', 'q', 'opac'),
            ('Google Books', 'https://www.google.com/search', 'q', 'opac'),
            ('WorldCat', 'https://www.worldcat.org/search', 'q', 'opac'),
            ('DOAJ – Directory of Open Access Journals', 'https://doaj.org/search/articles', 'query', 'api'),
        ]
        created = 0
        for name, base_url, param, lib_type in libs:
            _, c = ExternalLibrary.objects.get_or_create(
                name=name,
                defaults={'base_url': base_url, 'search_param': param, 'lib_type': lib_type, 'is_active': True},
            )
            if c:
                created += 1
        self.stdout.write(f'  External libraries: {created} created.')

    # ── NEWS ─────────────────────────────────────────────────────────────────

    def _seed_news(self):
        items = [
            (
                'Welcome to MSICT Online Library Management System',
                'The MSICT Library is pleased to announce the launch of the new Online Library Management System (OLMS). '
                'Members can now search the catalog, request books, track borrows, and access free digital resources online. '
                'Login with your army number credentials to get started.',
            ),
            (
                'Library Operating Hours',
                'The library is open Monday to Friday, 08:00 – 18:00 hrs, and Saturday 09:00 – 14:00 hrs. '
                'Members are reminded that all borrowed books must be returned by the due date to avoid fines of TZS 500 per day.',
            ),
            (
                'New Books Available – April 2024',
                'A new collection of ICT and Military Strategy books has been added to the library catalog. '
                'Topics include Cybersecurity, Artificial Intelligence, Cloud Computing, and Military Leadership. '
                'Visit the catalog to browse the new arrivals.',
            ),
            (
                'Interlibrary Loan (ILL) Service Now Available',
                'Members can now request books not available in our collection through the Interlibrary Loan service. '
                'Submit your ILL request through the portal and the library team will source the material from partner institutions.',
            ),
        ]
        created = 0
        for title, content in items:
            _, c = News.objects.get_or_create(title=title, defaults={'content': content, 'is_active': True})
            if c:
                created += 1
        self.stdout.write(f'  News items: {created} created.')

    # ── VENDORS ──────────────────────────────────────────────────────────────

    def _seed_vendors(self):
        vendors = [
            ('Text Book Centre Ltd', 'James Mwangi', 'tbc@textbookcentre.co.tz', '+255754000001', 'Dar es Salaam, Tanzania'),
            ('Tanzania Library Services Board', 'Dr. Amina Hassan', 'info@tlsb.go.tz', '+255222150001', 'Bibi Titi Mohamed Rd, Dar es Salaam'),
            ('Mkuki na Nyota Publishers', 'Said Mwafongo', 'info@mkukinanyota.com', '+255222150100', 'Plot 52, New Bagamoyo Road, Dar es Salaam'),
            ('Springer Nature Tanzania Rep', 'Linda Osei', 'springer.tz@rep.com', '+255754000099', 'Nairobi / Remote'),
            ('Oxford University Press East Africa', 'Patrick Kiiru', 'oup.ea@oup.com', '+254202210001', 'Nairobi, Kenya'),
        ]
        created = 0
        for name, contact, email, phone, address in vendors:
            _, c = Vendor.objects.get_or_create(
                name=name,
                defaults={'contact_person': contact, 'email': email, 'phone': phone, 'address': address},
            )
            if c:
                created += 1
        self.stdout.write(f'  Vendors: {created} created.')

    # ── BOOKS ────────────────────────────────────────────────────────────────

    def _seed_books(self):
        it_cat = Category.objects.filter(name='Information Technology').first()
        mil_cat = Category.objects.filter(name='Military & Defence').first()
        eng_cat = Category.objects.filter(name='Engineering').first()
        sci_cat = Category.objects.filter(name='Science & Technology').first()
        math_cat = Category.objects.filter(name='Mathematics').first()
        lead_cat = Category.objects.filter(name='Leadership').first()
        biz_cat = Category.objects.filter(name='Business & Management').first()
        sec_cat = Category.objects.filter(name='Law & Governance').first()

        bit_course = Course.objects.filter(course_name='Bachelor of Information Technology').first()
        bcs_course = Course.objects.filter(course_name='Bachelor of Computer Science').first()
        dip_course = Course.objects.filter(course_name='Diploma in ICT').first()
        mil_course = Course.objects.filter(course_name='Military Leadership Course').first()
        jcsc_course = Course.objects.filter(course_name='Junior Command and Staff Course').first()
        scsc_course = Course.objects.filter(course_name='Senior Command and Staff Course').first()
        ait_course = Course.objects.filter(course_name='Advanced ICT Officers Course').first()

        books_data = [
            # (isbn, title, author, publisher, year, category, summary, carousel, [courses])
            (
                '9780132126953', 'Computer Networks (5th Edition)',
                'Andrew S. Tanenbaum, David J. Wetherall',
                'Pearson Education', 2011, it_cat,
                'A comprehensive textbook covering all aspects of computer networking including data link layer, '
                'network layer, transport layer, and application layer protocols. Essential reading for ICT students.',
                True, [bit_course, bcs_course, dip_course],
            ),
            (
                '9780262033848', 'Introduction to Algorithms (3rd Edition)',
                'Thomas H. Cormen, Charles E. Leiserson, Ronald L. Rivest, Clifford Stein',
                'MIT Press', 2009, it_cat,
                'The definitive reference on algorithms and data structures. Covers sorting, searching, graph algorithms, '
                'dynamic programming, and advanced topics with rigorous mathematical analysis.',
                True, [bcs_course, bit_course],
            ),
            (
                '9781118063330', 'Operating System Concepts (9th Edition)',
                'Abraham Silberschatz, Peter B. Galvin, Greg Gagne',
                'Wiley', 2012, it_cat,
                'Known as the "Dinosaur Book", this is the standard text for operating systems courses worldwide. '
                'Covers process management, memory management, storage management, and distributed systems.',
                True, [bit_course, bcs_course, dip_course],
            ),
            (
                '9780073523323', 'Database System Concepts (6th Edition)',
                'Abraham Silberschatz, Henry F. Korth, S. Sudarshan',
                'McGraw-Hill', 2010, it_cat,
                'A leading database textbook covering relational model, SQL, database design, transaction management, '
                'concurrency control, and recovery systems. Ideal for all ICT degree programs.',
                True, [bit_course, bcs_course],
            ),
            (
                '9780134685991', 'Computer Organization and Architecture (10th Edition)',
                'William Stallings',
                'Pearson', 2016, eng_cat,
                'Covers the structure and function of computers from the digital logic level through instruction set '
                'architecture, processor design, memory hierarchy, and input/output. Recommended for engineering students.',
                True, [bit_course, bcs_course, dip_course],
            ),
            (
                '9780136042594', 'Artificial Intelligence: A Modern Approach (3rd Edition)',
                'Stuart Russell, Peter Norvig',
                'Pearson', 2009, it_cat,
                'The most comprehensive textbook on artificial intelligence. Covers search, knowledge representation, '
                'planning, learning, natural language processing, robotics, and perception.',
                True, [bcs_course, ait_course],
            ),
            (
                '9780471117094', 'The Art of War',
                'Sun Tzu (Trans. Lionel Giles)',
                'Wilder Publications', 500, mil_cat,
                'One of the oldest and most influential treatises on military strategy and tactics. '
                'A must-read for all military officers covering principles of warfare, espionage, and leadership.',
                False, [mil_course, jcsc_course, scsc_course],
            ),
            (
                '9781493625338', 'Cybersecurity Essentials',
                'Charles J. Brooks, Christopher Grow, Philip Craig, Donald Short',
                'Wiley', 2018, it_cat,
                'Provides a comprehensive introduction to cybersecurity covering threats, cryptography, network security, '
                'access control, and incident response. Aligned with CompTIA Security+ exam objectives.',
                False, [bit_course, bcs_course, ait_course],
            ),
            (
                '9781491946008', 'Python Crash Course (2nd Edition)',
                'Eric Matthes',
                'No Starch Press', 2019, it_cat,
                'A hands-on, project-based introduction to Python programming. Covers Python basics, then three '
                'real-world projects: a game, data visualizations, and a web application.',
                False, [bit_course, bcs_course, dip_course],
            ),
            (
                '9780073373454', 'Data Structures and Algorithm Analysis in C++ (4th Edition)',
                'Mark A. Weiss',
                'Pearson', 2013, it_cat,
                'Covers fundamental data structures including lists, stacks, queues, trees, and graphs, '
                'with analysis of the algorithms that operate on them. Uses C++ throughout.',
                False, [bcs_course, bit_course],
            ),
            (
                '9781119455363', 'Software Engineering: A Practitioner\'s Approach (9th Edition)',
                'Roger S. Pressman, Bruce Maxim',
                'McGraw-Hill', 2019, it_cat,
                'A classic text covering the full spectrum of software engineering — from requirements through design, '
                'coding, testing, and maintenance. Includes agile and DevOps perspectives.',
                False, [bit_course, bcs_course],
            ),
            (
                '9780073376011', 'Network Security Essentials (6th Edition)',
                'William Stallings',
                'Pearson', 2016, it_cat,
                'Covers key aspects of network security including cryptography, authentication, email security, '
                'IP security, web security, wireless network security, and system security.',
                False, [bit_course, ait_course],
            ),
            (
                '9780071840187', 'Digital Electronics: Principles, Devices and Applications',
                'Anil K. Maini',
                'Wiley', 2007, eng_cat,
                'Comprehensive treatment of digital electronics fundamentals — from Boolean algebra and logic gates '
                'through combinational circuits, sequential circuits, microprocessors, and memory.',
                False, [bit_course, dip_course],
            ),
            (
                '9780321537522', 'Discrete Mathematics and Its Applications (7th Edition)',
                'Kenneth H. Rosen',
                'McGraw-Hill', 2011, math_cat,
                'Covers logic, sets, functions, algorithms, number theory, combinatorics, graph theory, trees, '
                'and Boolean algebra. The standard text for discrete mathematics courses in computing.',
                False, [bcs_course, bit_course],
            ),
            (
                '9780321928429', 'Mathematics for Computer Science',
                'Eric Lehman, F. Thomson Leighton, Albert R. Meyer',
                'MIT OpenCourseWare', 2017, math_cat,
                'Covers mathematical proofs, induction, number theory, graph theory, probability, and combinatorics '
                'as applied to computer science. Freely available from MIT.',
                False, [bcs_course, bit_course],
            ),
            (
                '9780071086226', 'Cloud Computing: Concepts, Technology and Architecture',
                'Thomas Erl, Ricardo Puttini, Zaigham Mahmood',
                'Pearson', 2013, it_cat,
                'Establishes the definitive cloud computing terminology and covers cloud delivery models, '
                'deployment models, mechanisms, and governance. Essential for modern ICT professionals.',
                False, [bit_course, ait_course],
            ),
            (
                '9781491912058', 'Machine Learning with Python Cookbook',
                'Kyle Gallatin, Chris Albon',
                'O\'Reilly Media', 2023, it_cat,
                'Practical recipes covering the full machine learning workflow: data preprocessing, feature '
                'engineering, model selection, evaluation, and production deployment using scikit-learn and TensorFlow.',
                False, [bcs_course, ait_course],
            ),
            (
                '9780071782234', 'Management Information Systems (13th Edition)',
                'Kenneth C. Laudon, Jane P. Laudon',
                'Pearson', 2014, biz_cat,
                'Explores information systems in business, covering digital transformation, enterprise systems, '
                'e-commerce, decision support, knowledge management, and IT governance.',
                False, [bit_course, scsc_course],
            ),
            (
                '9780071840323', 'Military Leadership: In Pursuit of Excellence (7th Edition)',
                'Robert L. Taylor, William E. Rosenbach',
                'Westview Press', 2009, lead_cat,
                'Anthology of essential readings on military leadership covering leadership theory, ethics, '
                'leadership in combat, developing leaders, and the future of military leadership.',
                False, [mil_course, jcsc_course, scsc_course],
            ),
            (
                '9780684830421', 'On War (Vom Kriege)',
                'Carl von Clausewitz (Trans. Michael Howard)',
                'Princeton University Press', 1989, mil_cat,
                'The seminal work on military strategy by Prussian general Carl von Clausewitz. Introduces '
                'the concepts of friction, fog of war, and the political nature of warfare. Required reading for senior officers.',
                False, [scsc_course, jcsc_course],
            ),
            (
                '9780199783489', 'Information Security Management Handbook (6th Edition)',
                'Harold F. Tipton, Micki Krause Nozaki',
                'CRC Press', 2012, it_cat,
                'Comprehensive reference covering all domains of information security management including risk '
                'management, access control, cryptography, network security, and business continuity.',
                False, [ait_course, bit_course],
            ),
            (
                '9781593272906', 'The Linux Command Line (2nd Edition)',
                'William E. Shotts Jr.',
                'No Starch Press', 2019, it_cat,
                'A complete introduction to Linux command line tools, shell scripting, and system administration. '
                'Essential for ICT professionals managing Linux servers and systems.',
                False, [bit_course, bcs_course, dip_course],
            ),
            (
                '9780136091554', 'Computer Security: Art and Science (2nd Edition)',
                'Matt Bishop',
                'Addison-Wesley', 2018, it_cat,
                'Comprehensive, theory-based treatment of computer security including access control models, '
                'cryptography, authentication, malware, network security, and formal security models.',
                False, [bcs_course, ait_course],
            ),
            (
                '9780131103627', 'The C Programming Language (2nd Edition)',
                'Brian W. Kernighan, Dennis M. Ritchie',
                'Prentice Hall', 1988, it_cat,
                'The original and definitive reference for the C programming language by its creators. '
                'Covers all C language features with clear examples. Essential reference for systems programmers.',
                False, [bcs_course, bit_course, dip_course],
            ),
            (
                '9780735619678', 'Code Complete (2nd Edition)',
                'Steve McConnell',
                'Microsoft Press', 2004, it_cat,
                'Widely regarded as one of the best software construction books. Covers coding style, design '
                'patterns, testing, debugging, and the software development process with practical advice.',
                False, [bit_course, bcs_course],
            ),
        ]

        books_created = copies_created = 0
        accession_counter = 1

        for entry in books_data:
            isbn, title, author, publisher, year, category, summary, carousel, courses = entry

            book, created = Book.objects.get_or_create(
                isbn=isbn,
                defaults={
                    'title': title,
                    'author': author,
                    'publisher': publisher,
                    'year': year,
                    'category': category,
                    'summary': summary,
                    'show_in_carousel': carousel,
                },
            )
            if created:
                books_created += 1
                for course in courses:
                    if course:
                        book.courses.add(course)

            for i in range(3):
                acc = f'MSICT/{accession_counter:05d}'
                barcode = f'BC{accession_counter:07d}'
                shelf = f'SHELF-{chr(65 + (accession_counter % 8))}{(accession_counter % 20) + 1}'
                _, cc = BookCopy.objects.get_or_create(
                    accession_no=acc,
                    defaults={
                        'book': book,
                        'copy_type': 'hardcopy',
                        'status': 'available',
                        'shelf_location': shelf,
                        'barcode': barcode,
                    },
                )
                if cc:
                    copies_created += 1
                accession_counter += 1

        self.stdout.write(f'  Books: {books_created} created, {copies_created} hardcopies added.')

    # ── MEMBERS ──────────────────────────────────────────────────────────────

    def _seed_members(self):
        members_data = [
            {
                'army_no': 'S001/2024', 'registration_no': 'BIT/2024/001',
                'first_name': 'Juma', 'middle_name': 'Hassan', 'surname': 'Mwalimu',
                'role': 'member', 'member_type': 'student',
                'email': 'juma.mwalimu@msict.ac.tz', 'phone': '+255754001001',
            },
            {
                'army_no': 'S002/2024', 'registration_no': 'BIT/2024/002',
                'first_name': 'Fatuma', 'middle_name': '', 'surname': 'Ally',
                'role': 'member', 'member_type': 'student',
                'email': 'fatuma.ally@msict.ac.tz', 'phone': '+255754001002',
            },
            {
                'army_no': 'S003/2024', 'registration_no': 'BCS/2024/001',
                'first_name': 'Peter', 'middle_name': 'John', 'surname': 'Kimaro',
                'role': 'member', 'member_type': 'student',
                'email': 'peter.kimaro@msict.ac.tz', 'phone': '+255754001003',
            },
            {
                'army_no': 'S004/2024', 'registration_no': 'DIP/2024/001',
                'first_name': 'Amina', 'middle_name': 'Said', 'surname': 'Rashid',
                'role': 'member', 'member_type': 'student',
                'email': 'amina.rashid@msict.ac.tz', 'phone': '+255754001004',
            },
            {
                'army_no': 'S005/2024', 'registration_no': 'DIP/2024/002',
                'first_name': 'Emmanuel', 'middle_name': '', 'surname': 'Mwanga',
                'role': 'member', 'member_type': 'student',
                'email': 'emmanuel.mwanga@msict.ac.tz', 'phone': '+255754001005',
            },
            {
                'army_no': 'S006/2024', 'registration_no': 'MLC/2024/001',
                'first_name': 'George', 'middle_name': 'David', 'surname': 'Minja',
                'role': 'member', 'member_type': 'student',
                'email': 'george.minja@msict.ac.tz', 'phone': '+255754001006',
            },
            {
                'army_no': 'LEC001', 'registration_no': None,
                'first_name': 'Dr. Grace', 'middle_name': '', 'surname': 'Mwasumbi',
                'role': 'member', 'member_type': 'lecturer',
                'email': 'grace.mwasumbi@msict.ac.tz', 'phone': '+255754002001',
            },
            {
                'army_no': 'LEC002', 'registration_no': None,
                'first_name': 'Prof. Ali', 'middle_name': 'Seif', 'surname': 'Kombo',
                'role': 'member', 'member_type': 'lecturer',
                'email': 'ali.kombo@msict.ac.tz', 'phone': '+255754002002',
            },
            {
                'army_no': 'LEC003', 'registration_no': None,
                'first_name': 'Dr. Neema', 'middle_name': '', 'surname': 'Byarugaba',
                'role': 'member', 'member_type': 'lecturer',
                'email': 'neema.byarugaba@msict.ac.tz', 'phone': '+255754002003',
            },
            {
                'army_no': 'STF001', 'registration_no': None,
                'first_name': 'Rose', 'middle_name': '', 'surname': 'Nyambura',
                'role': 'member', 'member_type': 'staff',
                'email': 'rose.nyambura@msict.ac.tz', 'phone': '+255754003001',
            },
            {
                'army_no': 'STF002', 'registration_no': None,
                'first_name': 'Francis', 'middle_name': 'Joseph', 'surname': 'Ngowi',
                'role': 'member', 'member_type': 'staff',
                'email': 'francis.ngowi@msict.ac.tz', 'phone': '+255754003002',
            },
            {
                'army_no': 'LIB001', 'registration_no': None,
                'first_name': 'Halima', 'middle_name': 'Bakari', 'surname': 'Suleiman',
                'role': 'librarian', 'member_type': None,
                'email': 'halima.suleiman@msict.ac.tz', 'phone': '+255754004001',
            },
        ]

        created_count = 0
        for data in members_data:
            if OLMSUser.objects.filter(army_no=data['army_no']).exists():
                continue
            username = OLMSUser.generate_username(
                data['role'],
                data['member_type'],
                data['surname'],
                data.get('registration_no'),
            )
            base_username = username
            counter = 1
            while OLMSUser.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            password = OLMSUser.generate_initial_password(data['army_no'])
            if not password:
                password = 'Msict@2024'

            OLMSUser.objects.create_user(
                username=username,
                password=password,
                army_no=data['army_no'],
                registration_no=data.get('registration_no'),
                first_name=data['first_name'],
                middle_name=data.get('middle_name', ''),
                surname=data['surname'],
                role=data['role'],
                member_type=data['member_type'],
                email=data['email'],
                phone=data['phone'],
                is_staff=(data['role'] in ('admin', 'librarian')),
                last_password_change=timezone.now(),
            )
            created_count += 1

        self.stdout.write(f'  Members/Librarian: {created_count} created.')
