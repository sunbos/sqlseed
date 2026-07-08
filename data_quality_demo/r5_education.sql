-- Round 5: Online Education Platform (12 tables)
-- Compatible: SQLite + PostgreSQL
-- Exercises: Pattern 18 (conditional equality), Pattern 28 (conditional requirement),
--             date ordering, enum distributions, UNIQUE templates, cross-table FK
-- Note: SQLite enables FK via PRAGMA foreign_keys=ON at connection time.
--       PostgreSQL enables FK by default. AUTOINCREMENT is SQLite syntax;
--       PG equivalent: GENERATED ALWAYS AS IDENTITY.

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_code TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    role TEXT NOT NULL CHECK (role IN ('student', 'instructor', 'admin')),
    gender TEXT CHECK (gender IN ('male', 'female', 'other')),
    birth_date DATE,
    avatar_url TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'banned')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (phone IS NULL OR LENGTH(phone) = 11)
);

CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    parent_id INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0 CHECK (sort_order >= 0),
    FOREIGN KEY (parent_id) REFERENCES categories(id)
);

CREATE TABLE courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    instructor_id INTEGER NOT NULL,
    description TEXT,
    isbn TEXT CHECK (isbn IS NULL OR LENGTH(isbn) >= 10),
    slug TEXT NOT NULL UNIQUE CHECK (slug LIKE '%-%'),
    price REAL NOT NULL CHECK (price >= 0.0),
    original_price REAL CHECK (original_price >= 0.0),
    difficulty TEXT NOT NULL CHECK (difficulty IN ('beginner', 'intermediate', 'advanced')),
    duration_hours INTEGER NOT NULL CHECK (duration_hours > 0),
    max_students INTEGER CHECK (max_students IS NULL OR max_students > 0),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
    is_free INTEGER NOT NULL DEFAULT 0 CHECK (is_free IN (0, 1)),
    published_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(id),
    FOREIGN KEY (instructor_id) REFERENCES users(id),
    CHECK (original_price IS NULL OR original_price >= price),
    CHECK (is_free = 1 OR price < 100 OR original_price IS NULL OR original_price < 200)
);

CREATE TABLE lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    video_url TEXT,
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0 AND duration_minutes <= 300),
    sort_order INTEGER NOT NULL DEFAULT 1 CHECK (sort_order >= 1),
    is_preview INTEGER NOT NULL DEFAULT 0 CHECK (is_preview IN (0, 1)),
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
);

CREATE TABLE enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    course_id INTEGER NOT NULL,
    enrolled_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    progress_percent INTEGER NOT NULL DEFAULT 0 CHECK (progress_percent >= 0 AND progress_percent <= 100),
    last_lesson_id INTEGER,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'dropped', 'refunded')),
    FOREIGN KEY (student_id) REFERENCES users(id),
    FOREIGN KEY (course_id) REFERENCES courses(id),
    FOREIGN KEY (last_lesson_id) REFERENCES lessons(id),
    CHECK (completed_at IS NULL OR completed_at >= enrolled_at),
    CHECK (status != 'completed' OR progress_percent = 100),
    CHECK (status = 'active' AND progress_percent >= 0
           OR status = 'completed' AND progress_percent >= 100
           OR status = 'dropped' AND progress_percent < 100),
    CHECK (status IN ('dropped', 'refunded') OR completed_at IS NULL)
);

CREATE TABLE lesson_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    enrollment_id INTEGER NOT NULL,
    lesson_id INTEGER NOT NULL,
    watched_percent INTEGER NOT NULL DEFAULT 0 CHECK (watched_percent >= 0 AND watched_percent <= 100),
    watch_duration_seconds INTEGER NOT NULL DEFAULT 0 CHECK (watch_duration_seconds >= 0),
    last_position_seconds INTEGER NOT NULL DEFAULT 0 CHECK (last_position_seconds >= 0),
    is_completed INTEGER NOT NULL DEFAULT 0 CHECK (is_completed IN (0, 1)),
    completed_at DATETIME,
    first_watched_at DATETIME,
    FOREIGN KEY (enrollment_id) REFERENCES enrollments(id) ON DELETE CASCADE,
    FOREIGN KEY (lesson_id) REFERENCES lessons(id),
    CHECK (completed_at IS NULL OR first_watched_at IS NOT NULL),
    CHECK (completed_at IS NULL OR completed_at >= first_watched_at),
    CHECK (is_completed != 1 OR watched_percent = 100)
);

CREATE TABLE coupons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    discount_type TEXT NOT NULL CHECK (discount_type IN ('fixed', 'percentage')),
    discount_value REAL NOT NULL CHECK (discount_value > 0),
    min_order_amount REAL NOT NULL DEFAULT 0.0 CHECK (min_order_amount >= 0.0),
    max_discount_amount REAL,
    total_count INTEGER NOT NULL DEFAULT 100 CHECK (total_count > 0),
    used_count INTEGER NOT NULL DEFAULT 0 CHECK (used_count >= 0),
    start_at DATETIME NOT NULL,
    end_at DATETIME NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled', 'expired')),
    CHECK (end_at > start_at),
    CHECK (used_count <= total_count),
    CHECK (discount_type != 'percentage' OR discount_value <= 100),
    CHECK (max_discount_amount IS NULL OR max_discount_amount > 0)
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no TEXT NOT NULL UNIQUE,
    student_id INTEGER NOT NULL,
    course_id INTEGER NOT NULL,
    amount REAL NOT NULL CHECK (amount >= 0.0),
    discount_amount REAL NOT NULL DEFAULT 0.0 CHECK (discount_amount >= 0.0),
    pay_amount REAL NOT NULL CHECK (pay_amount >= 0.0),
    coupon_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'paid', 'cancelled', 'refunded')),
    paid_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(id),
    FOREIGN KEY (course_id) REFERENCES courses(id),
    FOREIGN KEY (coupon_id) REFERENCES coupons(id),
    CHECK (discount_amount <= amount),
    CHECK (pay_amount = amount - discount_amount),
    CHECK (status != 'paid' OR paid_at IS NOT NULL)
);

CREATE TABLE payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_no TEXT NOT NULL UNIQUE,
    order_id INTEGER NOT NULL,
    amount REAL NOT NULL CHECK (amount > 0.0),
    method TEXT NOT NULL CHECK (method IN ('alipay', 'wechat', 'card', 'bank_transfer')),
    transaction_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'success', 'failed', 'refunded')),
    paid_at DATETIME,
    refunded_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(id),
    CHECK (status != 'success' OR paid_at IS NOT NULL),
    CHECK (status != 'refunded' OR refunded_at IS NOT NULL),
    CHECK (refunded_at IS NULL OR refunded_at >= paid_at)
);

CREATE TABLE reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    content TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (course_id) REFERENCES courses(id),
    FOREIGN KEY (student_id) REFERENCES users(id)
);

CREATE TABLE certificates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cert_no TEXT NOT NULL UNIQUE,
    enrollment_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    course_id INTEGER NOT NULL,
    issued_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    verify_code TEXT NOT NULL UNIQUE,
    FOREIGN KEY (enrollment_id) REFERENCES enrollments(id),
    FOREIGN KEY (student_id) REFERENCES users(id),
    FOREIGN KEY (course_id) REFERENCES courses(id)
);

CREATE TABLE instructor_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instructor_id INTEGER NOT NULL UNIQUE,
    title TEXT NOT NULL,
    bio TEXT,
    expertise TEXT,
    years_teaching INTEGER NOT NULL DEFAULT 0 CHECK (years_teaching >= 0),
    total_students INTEGER NOT NULL DEFAULT 0 CHECK (total_students >= 0),
    avg_rating REAL NOT NULL DEFAULT 0.0 CHECK (avg_rating >= 0.0 AND avg_rating <= 5.0),
    FOREIGN KEY (instructor_id) REFERENCES users(id)
);

CREATE UNIQUE INDEX idx_enroll_active ON enrollments(student_id, course_id) WHERE status = 'active';
