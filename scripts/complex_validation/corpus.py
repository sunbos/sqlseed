"""Complex real-world schema corpus for zero-config validation.

11 databases modeled on real open-source / business schemas:
  chinook, northwind, sakila, hospital, banking, ecommerce,
  university, hr, logistics, forum, edge_cases.

Each schema: {"ddl": [...], "counts": {table: n | None(skip fill)}, "semantic": [(table, where_expr, desc)]}
Row counts respect composite-PK combination spaces.
"""

DEFAULT_COUNT = 100

SCHEMAS: dict[str, dict] = {}

# ── S1: chinook (music store, real open-source schema) ──────────────────────
SCHEMAS["chinook"] = {
    "ddl": [
        """CREATE TABLE artist (
            artist_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        )""",
        """CREATE TABLE album (
            album_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            artist_id INTEGER NOT NULL REFERENCES artist(artist_id)
        )""",
        """CREATE TABLE employee (
            employee_id INTEGER PRIMARY KEY,
            last_name TEXT NOT NULL,
            first_name TEXT NOT NULL,
            title TEXT,
            reports_to INTEGER REFERENCES employee(employee_id),
            birth_date DATE,
            hire_date DATE,
            email TEXT
        )""",
        """CREATE TABLE genre (
            genre_id INTEGER PRIMARY KEY,
            name TEXT
        )""",
        """CREATE TABLE media_type (
            media_type_id INTEGER PRIMARY KEY,
            name TEXT
        )""",
        """CREATE TABLE track (
            track_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            album_id INTEGER NOT NULL REFERENCES album(album_id),
            media_type_id INTEGER NOT NULL REFERENCES media_type(media_type_id),
            genre_id INTEGER REFERENCES genre(genre_id),
            composer TEXT,
            milliseconds INTEGER NOT NULL CHECK (milliseconds > 0),
            bytes INTEGER CHECK (bytes >= 0),
            unit_price NUMERIC NOT NULL CHECK (unit_price >= 0)
        )""",
        """CREATE TABLE customer (
            customer_id INTEGER PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            company TEXT,
            address TEXT,
            city TEXT,
            state TEXT,
            country TEXT,
            postal_code TEXT,
            phone TEXT,
            email TEXT NOT NULL,
            support_rep_id INTEGER REFERENCES employee(employee_id)
        )""",
        """CREATE TABLE invoice (
            invoice_id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES customer(customer_id),
            invoice_date DATETIME NOT NULL,
            billing_address TEXT,
            billing_city TEXT,
            billing_country TEXT,
            total NUMERIC NOT NULL CHECK (total >= 0)
        )""",
        """CREATE TABLE invoice_line (
            invoice_line_id INTEGER PRIMARY KEY,
            invoice_id INTEGER NOT NULL REFERENCES invoice(invoice_id),
            track_id INTEGER NOT NULL REFERENCES track(track_id),
            unit_price NUMERIC NOT NULL CHECK (unit_price >= 0),
            quantity INTEGER NOT NULL CHECK (quantity > 0)
        )""",
        """CREATE TABLE playlist (
            playlist_id INTEGER PRIMARY KEY,
            name TEXT
        )""",
        """CREATE TABLE playlist_track (
            playlist_id INTEGER NOT NULL REFERENCES playlist(playlist_id),
            track_id INTEGER NOT NULL REFERENCES track(track_id),
            PRIMARY KEY (playlist_id, track_id)
        )""",
    ],
    "counts": {
        "artist": 40, "album": 60, "employee": 8, "genre": 15, "media_type": 5,
        "track": 200, "customer": 50, "invoice": 150, "invoice_line": 300,
        "playlist": 10, "playlist_track": 100,
    },
    "semantic": [
        ("customer", "email LIKE '%@%'", "customer.email contains @"),
        ("employee", "email IS NULL OR email LIKE '%@%'", "employee.email contains @"),
    ],
}

# ── S2: northwind (trading, real open-source schema) ────────────────────────
SCHEMAS["northwind"] = {
    "ddl": [
        """CREATE TABLE category (
            category_id INTEGER PRIMARY KEY,
            category_name TEXT NOT NULL,
            description TEXT
        )""",
        """CREATE TABLE supplier (
            supplier_id INTEGER PRIMARY KEY,
            company_name TEXT NOT NULL,
            contact_name TEXT,
            country TEXT,
            phone TEXT
        )""",
        """CREATE TABLE product (
            product_id INTEGER PRIMARY KEY,
            product_name TEXT NOT NULL,
            supplier_id INTEGER REFERENCES supplier(supplier_id),
            category_id INTEGER REFERENCES category(category_id),
            unit_price REAL NOT NULL CHECK (unit_price >= 0),
            units_in_stock INTEGER NOT NULL CHECK (units_in_stock >= 0),
            reorder_level INTEGER NOT NULL CHECK (reorder_level >= 0),
            discontinued INTEGER NOT NULL CHECK (discontinued IN (0, 1))
        )""",
        """CREATE TABLE customer (
            customer_id INTEGER PRIMARY KEY,
            company_name TEXT NOT NULL,
            contact_name TEXT,
            country TEXT
        )""",
        """CREATE TABLE employee (
            employee_id INTEGER PRIMARY KEY,
            last_name TEXT NOT NULL,
            first_name TEXT NOT NULL,
            title TEXT,
            reports_to INTEGER REFERENCES employee(employee_id),
            hire_date DATE
        )""",
        """CREATE TABLE shipper (
            shipper_id INTEGER PRIMARY KEY,
            company_name TEXT NOT NULL,
            phone TEXT
        )""",
        """CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER REFERENCES customer(customer_id),
            employee_id INTEGER REFERENCES employee(employee_id),
            ship_via INTEGER REFERENCES shipper(shipper_id),
            order_date DATE NOT NULL,
            required_date DATE NOT NULL,
            shipped_date DATE,
            freight REAL NOT NULL CHECK (freight >= 0),
            CHECK (required_date >= order_date),
            CHECK (shipped_date IS NULL OR shipped_date >= order_date)
        )""",
        """CREATE TABLE order_details (
            order_id INTEGER NOT NULL REFERENCES orders(order_id),
            product_id INTEGER NOT NULL REFERENCES product(product_id),
            unit_price REAL NOT NULL CHECK (unit_price >= 0),
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            discount REAL NOT NULL CHECK (discount BETWEEN 0 AND 1),
            PRIMARY KEY (order_id, product_id)
        )""",
        """CREATE TABLE region (
            region_id INTEGER PRIMARY KEY,
            region_description TEXT NOT NULL
        )""",
        """CREATE TABLE territory (
            territory_id INTEGER PRIMARY KEY,
            territory_description TEXT NOT NULL,
            region_id INTEGER NOT NULL REFERENCES region(region_id)
        )""",
        """CREATE TABLE employee_territory (
            employee_id INTEGER NOT NULL REFERENCES employee(employee_id),
            territory_id INTEGER NOT NULL REFERENCES territory(territory_id),
            PRIMARY KEY (employee_id, territory_id)
        )""",
    ],
    "counts": {
        "category": 8, "supplier": 25, "product": 60, "customer": 40,
        "employee": 9, "shipper": 3, "orders": 120, "order_details": 250,
        "region": 4, "territory": 20, "employee_territory": 25,
    },
    "semantic": [],
}

# ── S3: sakila (DVD rental, MySQL official sample, cycle removed) ───────────
SCHEMAS["sakila"] = {
    "ddl": [
        """CREATE TABLE country (
            country_id INTEGER PRIMARY KEY,
            country TEXT NOT NULL
        )""",
        """CREATE TABLE city (
            city_id INTEGER PRIMARY KEY,
            city TEXT NOT NULL,
            country_id INTEGER NOT NULL REFERENCES country(country_id)
        )""",
        """CREATE TABLE address (
            address_id INTEGER PRIMARY KEY,
            address TEXT NOT NULL,
            district TEXT,
            city_id INTEGER NOT NULL REFERENCES city(city_id),
            postal_code TEXT,
            phone TEXT
        )""",
        """CREATE TABLE store (
            store_id INTEGER PRIMARY KEY,
            address_id INTEGER NOT NULL REFERENCES address(address_id)
        )""",
        """CREATE TABLE staff (
            staff_id INTEGER PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            address_id INTEGER NOT NULL REFERENCES address(address_id),
            store_id INTEGER NOT NULL REFERENCES store(store_id),
            email TEXT,
            active INTEGER NOT NULL CHECK (active IN (0, 1))
        )""",
        """CREATE TABLE customer (
            customer_id INTEGER PRIMARY KEY,
            store_id INTEGER NOT NULL REFERENCES store(store_id),
            address_id INTEGER NOT NULL REFERENCES address(address_id),
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            create_date DATE NOT NULL
        )""",
        """CREATE TABLE language (
            language_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        )""",
        """CREATE TABLE film (
            film_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            language_id INTEGER NOT NULL REFERENCES language(language_id),
            rental_duration INTEGER NOT NULL CHECK (rental_duration > 0),
            rental_rate NUMERIC NOT NULL CHECK (rental_rate >= 0),
            length INTEGER CHECK (length > 0),
            replacement_cost NUMERIC NOT NULL CHECK (replacement_cost >= 0),
            rating TEXT NOT NULL CHECK (rating IN ('G', 'PG', 'PG-13', 'R', 'NC-17'))
        )""",
        """CREATE TABLE actor (
            actor_id INTEGER PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL
        )""",
        """CREATE TABLE film_actor (
            actor_id INTEGER NOT NULL REFERENCES actor(actor_id),
            film_id INTEGER NOT NULL REFERENCES film(film_id),
            PRIMARY KEY (actor_id, film_id)
        )""",
        """CREATE TABLE category (
            category_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        )""",
        """CREATE TABLE film_category (
            film_id INTEGER NOT NULL REFERENCES film(film_id),
            category_id INTEGER NOT NULL REFERENCES category(category_id),
            PRIMARY KEY (film_id, category_id)
        )""",
        """CREATE TABLE inventory (
            inventory_id INTEGER PRIMARY KEY,
            film_id INTEGER NOT NULL REFERENCES film(film_id),
            store_id INTEGER NOT NULL REFERENCES store(store_id)
        )""",
        """CREATE TABLE rental (
            rental_id INTEGER PRIMARY KEY,
            rental_date DATETIME NOT NULL,
            inventory_id INTEGER NOT NULL REFERENCES inventory(inventory_id),
            customer_id INTEGER NOT NULL REFERENCES customer(customer_id),
            staff_id INTEGER NOT NULL REFERENCES staff(staff_id),
            return_date DATETIME,
            CHECK (return_date IS NULL OR return_date >= rental_date)
        )""",
        """CREATE TABLE payment (
            payment_id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES customer(customer_id),
            staff_id INTEGER NOT NULL REFERENCES staff(staff_id),
            rental_id INTEGER REFERENCES rental(rental_id),
            amount NUMERIC NOT NULL CHECK (amount >= 0),
            payment_date DATETIME NOT NULL
        )""",
    ],
    "counts": {
        "country": 20, "city": 40, "address": 60, "store": 2, "staff": 5,
        "customer": 80, "language": 6, "film": 100, "actor": 60,
        "film_actor": 250, "category": 16, "film_category": 200,
        "inventory": 150, "rental": 300, "payment": 300,
    },
    "semantic": [
        ("staff", "email IS NULL OR email LIKE '%@%'", "staff.email contains @"),
        ("customer", "email IS NULL OR email LIKE '%@%'", "customer.email contains @"),
    ],
}

# ── S4: hospital ─────────────────────────────────────────────────────────────
SCHEMAS["hospital"] = {
    "ddl": [
        """CREATE TABLE department (
            department_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            building TEXT
        )""",
        """CREATE TABLE doctor (
            doctor_id INTEGER PRIMARY KEY,
            department_id INTEGER NOT NULL REFERENCES department(department_id),
            full_name TEXT NOT NULL,
            license_no TEXT NOT NULL UNIQUE,
            specialty TEXT,
            hire_date DATE
        )""",
        """CREATE TABLE patient (
            patient_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            birth_date DATE NOT NULL,
            blood_type TEXT NOT NULL CHECK (blood_type IN ('A', 'B', 'AB', 'O')),
            insurance_no TEXT UNIQUE,
            phone TEXT
        )""",
        """CREATE TABLE ward (
            ward_id INTEGER PRIMARY KEY,
            department_id INTEGER NOT NULL REFERENCES department(department_id),
            ward_no TEXT NOT NULL,
            capacity INTEGER NOT NULL CHECK (capacity > 0)
        )""",
        """CREATE TABLE appointment (
            appointment_id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL REFERENCES patient(patient_id),
            doctor_id INTEGER NOT NULL REFERENCES doctor(doctor_id),
            scheduled_start DATETIME NOT NULL,
            scheduled_end DATETIME NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('SCHEDULED', 'COMPLETED', 'CANCELLED', 'NO_SHOW')),
            CHECK (scheduled_end > scheduled_start)
        )""",
        """CREATE TABLE prescription (
            prescription_id INTEGER PRIMARY KEY,
            appointment_id INTEGER NOT NULL REFERENCES appointment(appointment_id),
            medication TEXT NOT NULL,
            dosage_mg REAL NOT NULL CHECK (dosage_mg > 0),
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            CHECK (end_date >= start_date)
        )""",
        """CREATE TABLE admission (
            admission_id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL REFERENCES patient(patient_id),
            ward_id INTEGER NOT NULL REFERENCES ward(ward_id),
            admit_date DATETIME NOT NULL,
            discharge_date DATETIME,
            CHECK (discharge_date IS NULL OR discharge_date >= admit_date)
        )""",
        """CREATE TABLE invoice (
            invoice_id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL REFERENCES patient(patient_id),
            issued_date DATE NOT NULL,
            total NUMERIC NOT NULL CHECK (total >= 0),
            paid NUMERIC NOT NULL CHECK (paid >= 0),
            CHECK (paid <= total)
        )""",
    ],
    "counts": {
        "department": 10, "doctor": 30, "patient": 100, "ward": 15,
        "appointment": 200, "prescription": 250, "admission": 80, "invoice": 120,
    },
    "semantic": [],
}

# ── S5: banking ──────────────────────────────────────────────────────────────
SCHEMAS["banking"] = {
    "ddl": [
        """CREATE TABLE branch (
            branch_id INTEGER PRIMARY KEY,
            branch_name TEXT NOT NULL,
            city TEXT,
            swift_code TEXT UNIQUE
        )""",
        """CREATE TABLE customer (
            customer_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            ssn TEXT UNIQUE,
            email TEXT,
            date_of_birth DATE
        )""",
        """CREATE TABLE account (
            account_id INTEGER PRIMARY KEY,
            branch_id INTEGER NOT NULL REFERENCES branch(branch_id),
            customer_id INTEGER NOT NULL REFERENCES customer(customer_id),
            account_number TEXT NOT NULL UNIQUE,
            account_type TEXT NOT NULL CHECK (account_type IN ('CHECKING', 'SAVINGS', 'CREDIT', 'LOAN')),
            balance NUMERIC NOT NULL CHECK (balance >= 0),
            opened_date DATE
        )""",
        """CREATE TABLE card (
            card_id INTEGER PRIMARY KEY,
            account_id INTEGER NOT NULL REFERENCES account(account_id),
            card_number TEXT NOT NULL UNIQUE,
            card_type TEXT NOT NULL CHECK (card_type IN ('DEBIT', 'CREDIT')),
            expiry_date DATE,
            cvv TEXT,
            daily_limit NUMERIC CHECK (daily_limit > 0)
        )""",
        """CREATE TABLE loan (
            loan_id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES customer(customer_id),
            branch_id INTEGER NOT NULL REFERENCES branch(branch_id),
            principal NUMERIC NOT NULL CHECK (principal > 0),
            interest_rate REAL NOT NULL CHECK (interest_rate BETWEEN 0 AND 1),
            term_months INTEGER NOT NULL CHECK (term_months > 0),
            start_date DATE
        )""",
        """CREATE TABLE txn (
            txn_id INTEGER PRIMARY KEY,
            account_id INTEGER NOT NULL REFERENCES account(account_id),
            txn_type TEXT NOT NULL CHECK (txn_type IN ('DEBIT', 'CREDIT')),
            amount NUMERIC NOT NULL CHECK (amount != 0),
            txn_date DATETIME NOT NULL
        )""",
        """CREATE TABLE transfer (
            transfer_id INTEGER PRIMARY KEY,
            from_account_id INTEGER NOT NULL REFERENCES account(account_id),
            to_account_id INTEGER NOT NULL REFERENCES account(account_id),
            amount NUMERIC NOT NULL CHECK (amount > 0),
            transfer_date DATETIME NOT NULL,
            CHECK (from_account_id != to_account_id)
        )""",
    ],
    "counts": {
        "branch": 10, "customer": 80, "account": 120, "card": 100,
        "loan": 60, "txn": 400, "transfer": 200,
    },
    "semantic": [
        ("customer", "email IS NULL OR email LIKE '%@%'", "customer.email contains @"),
    ],
}

# ── S6: ecommerce ────────────────────────────────────────────────────────────
SCHEMAS["ecommerce"] = {
    "ddl": [
        """CREATE TABLE users (
            user_id INTEGER PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at DATETIME NOT NULL
        )""",
        """CREATE TABLE address (
            address_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(user_id),
            street TEXT,
            city TEXT,
            state TEXT,
            zip_code TEXT,
            country TEXT,
            is_default INTEGER NOT NULL CHECK (is_default IN (0, 1))
        )""",
        """CREATE TABLE category (
            category_id INTEGER PRIMARY KEY,
            parent_id INTEGER REFERENCES category(category_id),
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE
        )""",
        """CREATE TABLE product (
            product_id INTEGER PRIMARY KEY,
            category_id INTEGER NOT NULL REFERENCES category(category_id),
            sku TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            price NUMERIC NOT NULL CHECK (price > 0),
            stock INTEGER NOT NULL CHECK (stock >= 0),
            weight_kg REAL CHECK (weight_kg >= 0)
        )""",
        """CREATE TABLE coupon (
            coupon_id INTEGER PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            discount_pct INTEGER NOT NULL CHECK (discount_pct BETWEEN 1 AND 100),
            valid_from DATE NOT NULL,
            valid_until DATE NOT NULL,
            CHECK (valid_until > valid_from)
        )""",
        """CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(user_id),
            address_id INTEGER NOT NULL REFERENCES address(address_id),
            coupon_id INTEGER REFERENCES coupon(coupon_id),
            status TEXT NOT NULL CHECK (status IN ('PENDING', 'PAID', 'SHIPPED', 'DELIVERED', 'CANCELLED')),
            created_at DATETIME NOT NULL,
            total NUMERIC NOT NULL CHECK (total >= 0)
        )""",
        """CREATE TABLE order_item (
            order_item_id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES orders(order_id),
            product_id INTEGER NOT NULL REFERENCES product(product_id),
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            unit_price NUMERIC NOT NULL CHECK (unit_price >= 0)
        )""",
        """CREATE TABLE payment (
            payment_id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES orders(order_id),
            method TEXT NOT NULL CHECK (method IN ('CARD', 'PAYPAL', 'BANK_TRANSFER', 'CRYPTO')),
            amount NUMERIC NOT NULL CHECK (amount > 0),
            paid_at DATETIME
        )""",
        """CREATE TABLE review (
            review_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(user_id),
            product_id INTEGER NOT NULL REFERENCES product(product_id),
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            comment TEXT,
            created_at DATETIME,
            UNIQUE (user_id, product_id)
        )""",
    ],
    "counts": {
        "users": 60, "address": 80, "category": 20, "product": 80,
        "coupon": 15, "orders": 150, "order_item": 350, "payment": 150,
        "review": 120,
    },
    "semantic": [
        ("users", "email LIKE '%@%'", "users.email contains @"),
    ],
}

# ── S7: university (composite FK, self-ref prerequisite) ────────────────────
SCHEMAS["university"] = {
    "ddl": [
        """CREATE TABLE department (
            department_id INTEGER PRIMARY KEY,
            dept_name TEXT NOT NULL UNIQUE,
            building TEXT,
            budget NUMERIC CHECK (budget > 0)
        )""",
        """CREATE TABLE professor (
            professor_id INTEGER PRIMARY KEY,
            department_id INTEGER NOT NULL REFERENCES department(department_id),
            full_name TEXT NOT NULL,
            email TEXT UNIQUE,
            rank TEXT NOT NULL CHECK (rank IN ('ASSISTANT', 'ASSOCIATE', 'FULL')),
            hire_date DATE
        )""",
        """CREATE TABLE student (
            student_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE,
            gpa REAL CHECK (gpa BETWEEN 0 AND 4.0),
            enrollment_date DATE
        )""",
        """CREATE TABLE course (
            course_id INTEGER PRIMARY KEY,
            department_id INTEGER NOT NULL REFERENCES department(department_id),
            course_code TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            credits INTEGER NOT NULL CHECK (credits BETWEEN 1 AND 6)
        )""",
        """CREATE TABLE prerequisite (
            course_id INTEGER NOT NULL REFERENCES course(course_id),
            prereq_id INTEGER NOT NULL REFERENCES course(course_id),
            PRIMARY KEY (course_id, prereq_id),
            CHECK (course_id != prereq_id)
        )""",
        """CREATE TABLE classroom (
            building TEXT NOT NULL,
            room_no TEXT NOT NULL,
            capacity INTEGER NOT NULL CHECK (capacity > 0),
            PRIMARY KEY (building, room_no)
        )""",
        """CREATE TABLE section (
            section_id INTEGER PRIMARY KEY,
            course_id INTEGER NOT NULL REFERENCES course(course_id),
            professor_id INTEGER NOT NULL REFERENCES professor(professor_id),
            building TEXT NOT NULL,
            room_no TEXT NOT NULL,
            semester TEXT NOT NULL CHECK (semester IN ('FALL', 'SPRING', 'SUMMER')),
            year INTEGER NOT NULL CHECK (year BETWEEN 2000 AND 2030),
            FOREIGN KEY (building, room_no) REFERENCES classroom(building, room_no)
        )""",
        """CREATE TABLE enrollment (
            student_id INTEGER NOT NULL REFERENCES student(student_id),
            course_id INTEGER NOT NULL REFERENCES course(course_id),
            semester TEXT NOT NULL,
            grade TEXT CHECK (grade IN ('A', 'B', 'C', 'D', 'F')),
            UNIQUE (student_id, course_id, semester)
        )""",
    ],
    "counts": {
        "department": 8, "professor": 25, "student": 120, "course": 40,
        "prerequisite": 50, "classroom": 20, "section": 60, "enrollment": 300,
    },
    "semantic": [
        ("professor", "email IS NULL OR email LIKE '%@%'", "professor.email contains @"),
        ("student", "email IS NULL OR email LIKE '%@%'", "student.email contains @"),
    ],
}

# ── S8: hr (MySQL employees sample, heavy date-range CHECKs, TEXT PK) ───────
SCHEMAS["hr"] = {
    "ddl": [
        """CREATE TABLE departments (
            dept_no TEXT PRIMARY KEY,
            dept_name TEXT NOT NULL UNIQUE
        )""",
        """CREATE TABLE employees (
            emp_no INTEGER PRIMARY KEY,
            birth_date DATE NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            gender TEXT NOT NULL CHECK (gender IN ('M', 'F')),
            hire_date DATE NOT NULL,
            CHECK (hire_date > birth_date)
        )""",
        """CREATE TABLE dept_manager (
            dept_no TEXT NOT NULL REFERENCES departments(dept_no),
            emp_no INTEGER NOT NULL REFERENCES employees(emp_no),
            from_date DATE NOT NULL,
            to_date DATE NOT NULL,
            CHECK (to_date > from_date),
            PRIMARY KEY (dept_no, emp_no)
        )""",
        """CREATE TABLE dept_emp (
            emp_no INTEGER NOT NULL REFERENCES employees(emp_no),
            dept_no TEXT NOT NULL REFERENCES departments(dept_no),
            from_date DATE NOT NULL,
            to_date DATE NOT NULL,
            CHECK (to_date > from_date),
            PRIMARY KEY (emp_no, dept_no)
        )""",
        """CREATE TABLE salaries (
            emp_no INTEGER NOT NULL REFERENCES employees(emp_no),
            salary INTEGER NOT NULL CHECK (salary > 0),
            from_date DATE NOT NULL,
            to_date DATE NOT NULL,
            CHECK (to_date > from_date),
            PRIMARY KEY (emp_no, from_date)
        )""",
        """CREATE TABLE titles (
            emp_no INTEGER NOT NULL REFERENCES employees(emp_no),
            title TEXT NOT NULL,
            from_date DATE NOT NULL,
            to_date DATE,
            CHECK (to_date IS NULL OR to_date > from_date),
            PRIMARY KEY (emp_no, title, from_date)
        )""",
    ],
    "counts": {
        "departments": 9, "employees": 100, "dept_manager": 24,
        "dept_emp": 150, "salaries": 250, "titles": 150,
    },
    "semantic": [],
}

# ── S9: logistics ────────────────────────────────────────────────────────────
SCHEMAS["logistics"] = {
    "ddl": [
        """CREATE TABLE hub (
            hub_id INTEGER PRIMARY KEY,
            hub_code TEXT NOT NULL UNIQUE,
            city TEXT,
            country TEXT
        )""",
        """CREATE TABLE vehicle (
            vehicle_id INTEGER PRIMARY KEY,
            hub_id INTEGER NOT NULL REFERENCES hub(hub_id),
            plate_no TEXT NOT NULL UNIQUE,
            vehicle_type TEXT NOT NULL CHECK (vehicle_type IN ('VAN', 'TRUCK', 'SEMI')),
            capacity_kg INTEGER NOT NULL CHECK (capacity_kg > 0)
        )""",
        """CREATE TABLE driver (
            driver_id INTEGER PRIMARY KEY,
            hub_id INTEGER NOT NULL REFERENCES hub(hub_id),
            full_name TEXT NOT NULL,
            license_no TEXT UNIQUE,
            phone TEXT
        )""",
        """CREATE TABLE shipment (
            shipment_id INTEGER PRIMARY KEY,
            origin_hub_id INTEGER NOT NULL REFERENCES hub(hub_id),
            dest_hub_id INTEGER NOT NULL REFERENCES hub(hub_id),
            status TEXT NOT NULL CHECK (status IN ('CREATED', 'IN_TRANSIT', 'DELIVERED', 'EXCEPTION')),
            weight_kg REAL NOT NULL CHECK (weight_kg > 0),
            created_at DATETIME NOT NULL,
            eta DATETIME,
            CHECK (origin_hub_id != dest_hub_id)
        )""",
        """CREATE TABLE package (
            package_id INTEGER PRIMARY KEY,
            shipment_id INTEGER NOT NULL REFERENCES shipment(shipment_id),
            weight_kg REAL NOT NULL CHECK (weight_kg > 0),
            declared_value NUMERIC CHECK (declared_value >= 0),
            fragile INTEGER NOT NULL CHECK (fragile IN (0, 1))
        )""",
        """CREATE TABLE route_stop (
            shipment_id INTEGER NOT NULL REFERENCES shipment(shipment_id),
            seq INTEGER NOT NULL CHECK (seq > 0),
            hub_id INTEGER NOT NULL REFERENCES hub(hub_id),
            arrived_at DATETIME,
            PRIMARY KEY (shipment_id, seq)
        )""",
        """CREATE TABLE delivery (
            delivery_id INTEGER PRIMARY KEY,
            package_id INTEGER NOT NULL REFERENCES package(package_id),
            driver_id INTEGER NOT NULL REFERENCES driver(driver_id),
            vehicle_id INTEGER NOT NULL REFERENCES vehicle(vehicle_id),
            delivered_at DATETIME NOT NULL,
            signed_by TEXT
        )""",
    ],
    "counts": {
        "hub": 12, "vehicle": 30, "driver": 40, "shipment": 150,
        "package": 300, "route_stop": 400, "delivery": 250,
    },
    "semantic": [],
}

# ── S10: forum (Discourse-style, self-ref post replies) ─────────────────────
SCHEMAS["forum"] = {
    "ddl": [
        """CREATE TABLE users (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            trust_level INTEGER NOT NULL CHECK (trust_level BETWEEN 0 AND 4),
            created_at DATETIME NOT NULL
        )""",
        """CREATE TABLE category (
            category_id INTEGER PRIMARY KEY,
            parent_id INTEGER REFERENCES category(category_id),
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            position INTEGER NOT NULL CHECK (position >= 0)
        )""",
        """CREATE TABLE topic (
            topic_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(user_id),
            category_id INTEGER NOT NULL REFERENCES category(category_id),
            title TEXT NOT NULL,
            pinned INTEGER NOT NULL CHECK (pinned IN (0, 1)),
            views INTEGER NOT NULL CHECK (views >= 0),
            created_at DATETIME NOT NULL
        )""",
        """CREATE TABLE post (
            post_id INTEGER PRIMARY KEY,
            topic_id INTEGER NOT NULL REFERENCES topic(topic_id),
            user_id INTEGER NOT NULL REFERENCES users(user_id),
            reply_to_post_id INTEGER REFERENCES post(post_id),
            post_number INTEGER NOT NULL CHECK (post_number > 0),
            likes INTEGER NOT NULL CHECK (likes >= 0),
            created_at DATETIME NOT NULL
        )""",
        """CREATE TABLE tag (
            tag_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )""",
        """CREATE TABLE topic_tag (
            topic_id INTEGER NOT NULL REFERENCES topic(topic_id),
            tag_id INTEGER NOT NULL REFERENCES tag(tag_id),
            PRIMARY KEY (topic_id, tag_id)
        )""",
        """CREATE TABLE post_like (
            user_id INTEGER NOT NULL REFERENCES users(user_id),
            post_id INTEGER NOT NULL REFERENCES post(post_id),
            created_at DATETIME NOT NULL,
            PRIMARY KEY (user_id, post_id)
        )""",
    ],
    "counts": {
        "users": 60, "category": 15, "topic": 100, "post": 400,
        "tag": 20, "topic_tag": 200, "post_like": 300,
    },
    "semantic": [
        ("users", "email LIKE '%@%'", "users.email contains @"),
    ],
}

# ── S11: edge_cases (reserved words, naming styles, BLOB, wide, perf, cycles) ─
_wide_cols = ",\n".join(
    f"col_{i:02d} {'INTEGER' if i % 3 == 0 else ('REAL' if i % 3 == 1 else 'TEXT')}"
    for i in range(1, 39)
)
SCHEMAS["edge_cases"] = {
    "ddl": [
        """CREATE TABLE "order" (
            order_id INTEGER PRIMARY KEY,
            sOrderNo TEXT NOT NULL,
            userName TEXT,
            isActive INTEGER NOT NULL CHECK (isActive IN (0, 1)),
            totalAmount REAL NOT NULL CHECK (totalAmount >= 0)
        )""",
        """CREATE TABLE blob_store (
            blob_id INTEGER PRIMARY KEY,
            file_name TEXT NOT NULL,
            content BLOB,
            size_bytes INTEGER CHECK (size_bytes >= 0)
        )""",
        f"""CREATE TABLE wide_table (
            wide_id INTEGER PRIMARY KEY,
            {_wide_cols}
        )""",
        """CREATE TABLE events (
            event_id INTEGER PRIMARY KEY,
            event_type TEXT NOT NULL,
            payload TEXT,
            severity INTEGER NOT NULL CHECK (severity BETWEEN 1 AND 5),
            created_at DATETIME NOT NULL
        )""",
        """CREATE TABLE maybe_parent (
            parent_id INTEGER PRIMARY KEY,
            label TEXT
        )""",
        """CREATE TABLE optional_child (
            child_id INTEGER PRIMARY KEY,
            parent_id INTEGER REFERENCES maybe_parent(parent_id),
            note TEXT
        )""",
        """CREATE TABLE cycle_a (
            a_id INTEGER PRIMARY KEY,
            b_id INTEGER REFERENCES cycle_b(b_id),
            name TEXT
        )""",
        """CREATE TABLE cycle_b (
            b_id INTEGER PRIMARY KEY,
            a_id INTEGER REFERENCES cycle_a(a_id),
            name TEXT
        )""",
    ],
    "counts": {
        "order": 60, "blob_store": 40, "wide_table": 30, "events": 20000,
        "maybe_parent": None, "optional_child": 50, "cycle_a": 30, "cycle_b": 30,
    },
    "semantic": [],
}
