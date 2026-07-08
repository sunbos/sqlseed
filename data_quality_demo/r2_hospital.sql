-- Round 2: Hospital Information System (12 tables)
-- Exercises: Department hierarchy, doctor scheduling, appointment state machine,
--             prescription dosage, conditional NULL, cross-column date/time

PRAGMA foreign_keys = ON;

CREATE TABLE departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dept_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    parent_id INTEGER,
    dept_type TEXT NOT NULL CHECK (dept_type IN ('clinical', 'administrative', 'lab', 'pharmacy', 'emergency')),
    floor INTEGER CHECK (floor >= 1 AND floor <= 50),
    phone TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'merged', 'closed')),
    FOREIGN KEY (parent_id) REFERENCES departments(id),
    CHECK (phone IS NULL OR LENGTH(phone) >= 7)
);

CREATE TABLE doctors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    department_id INTEGER NOT NULL,
    title TEXT NOT NULL CHECK (title IN ('resident', 'attending', 'associate_chief', 'chief')),
    gender TEXT CHECK (gender IN ('male', 'female')),
    phone TEXT NOT NULL,
    email TEXT,
    hire_date DATE NOT NULL,
    license_no TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'on_leave', 'resigned')),
    FOREIGN KEY (department_id) REFERENCES departments(id),
    CHECK (LENGTH(phone) >= 7)
);

CREATE TABLE nurses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nurse_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    department_id INTEGER NOT NULL,
    rank TEXT NOT NULL CHECK (rank IN ('junior', 'senior', 'head')),
    phone TEXT NOT NULL,
    shift TEXT NOT NULL DEFAULT 'day' CHECK (shift IN ('day', 'night', 'rotating')),
    hire_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'on_leave', 'resigned')),
    FOREIGN KEY (department_id) REFERENCES departments(id),
    CHECK (LENGTH(phone) >= 7)
);

CREATE TABLE patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    id_card_no TEXT NOT NULL UNIQUE,
    gender TEXT NOT NULL CHECK (gender IN ('male', 'female')),
    birth_date DATE,
    phone TEXT NOT NULL,
    address TEXT,
    blood_type TEXT CHECK (blood_type IN ('A', 'B', 'AB', 'O')),
    allergy_history TEXT,
    emergency_contact TEXT,
    emergency_phone TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'admitted', 'discharged')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (LENGTH(phone) >= 7),
    CHECK (emergency_phone IS NULL OR LENGTH(emergency_phone) >= 7)
);

CREATE TABLE shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shift_code TEXT NOT NULL UNIQUE,
    doctor_id INTEGER NOT NULL,
    shift_date DATE NOT NULL,
    start_time TEXT NOT NULL CHECK (start_time LIKE '__:__'),
    end_time TEXT NOT NULL CHECK (end_time LIKE '__:__'),
    max_patients INTEGER NOT NULL DEFAULT 20 CHECK (max_patients > 0 AND max_patients <= 100),
    booked_count INTEGER NOT NULL DEFAULT 0 CHECK (booked_count >= 0),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'full', 'closed', 'cancelled')),
    FOREIGN KEY (doctor_id) REFERENCES doctors(id),
    CHECK (booked_count <= max_patients),
    CHECK (end_time > start_time)
);

CREATE TABLE appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    appt_no TEXT NOT NULL UNIQUE,
    patient_id INTEGER NOT NULL,
    doctor_id INTEGER NOT NULL,
    shift_id INTEGER NOT NULL,
    department_id INTEGER NOT NULL,
    appt_date DATE NOT NULL,
    appt_time TEXT NOT NULL CHECK (appt_time LIKE '__:__'),
    sequence_no INTEGER NOT NULL CHECK (sequence_no > 0),
    visit_type TEXT NOT NULL CHECK (visit_type IN ('first_visit', 'follow_up', 'emergency', 'consultation')),
    status TEXT NOT NULL DEFAULT 'booked' CHECK (status IN ('booked', 'checked_in', 'in_consultation', 'completed', 'cancelled', 'no_show')),
    check_in_time DATETIME,
    consultation_start DATETIME,
    consultation_end DATETIME,
    cancel_reason TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id),
    FOREIGN KEY (doctor_id) REFERENCES doctors(id),
    FOREIGN KEY (shift_id) REFERENCES shifts(id),
    FOREIGN KEY (department_id) REFERENCES departments(id),
    CHECK (status != 'checked_in' OR check_in_time IS NOT NULL),
    CHECK (status != 'in_consultation' OR consultation_start IS NOT NULL),
    CHECK (status != 'completed' OR consultation_end IS NOT NULL),
    CHECK (consultation_end IS NULL OR consultation_end >= consultation_start)
);

CREATE TABLE medical_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_no TEXT NOT NULL UNIQUE,
    patient_id INTEGER NOT NULL,
    doctor_id INTEGER NOT NULL,
    appointment_id INTEGER,
    visit_date DATE NOT NULL,
    chief_complaint TEXT NOT NULL,
    present_illness TEXT,
    past_history TEXT,
    physical_exam TEXT,
    diagnosis TEXT NOT NULL,
    diagnosis_code TEXT,
    temperature REAL CHECK (temperature IS NULL OR (temperature >= 35.0 AND temperature <= 42.0)),
    blood_pressure_high INTEGER CHECK (blood_pressure_high IS NULL OR (blood_pressure_high >= 60 AND blood_pressure_high <= 250)),
    blood_pressure_low INTEGER CHECK (blood_pressure_low IS NULL OR (blood_pressure_low >= 40 AND blood_pressure_low <= 150)),
    heart_rate INTEGER CHECK (heart_rate IS NULL OR (heart_rate >= 30 AND heart_rate <= 220)),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id),
    FOREIGN KEY (doctor_id) REFERENCES doctors(id),
    FOREIGN KEY (appointment_id) REFERENCES appointments(id),
    CHECK (blood_pressure_low IS NULL OR blood_pressure_low < blood_pressure_high)
);

CREATE TABLE prescriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prescription_no TEXT NOT NULL UNIQUE,
    record_id INTEGER NOT NULL,
    patient_id INTEGER NOT NULL,
    doctor_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'dispensed', 'cancelled')),
    prescribed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dispensed_at DATETIME,
    pharmacist_id INTEGER,
    FOREIGN KEY (record_id) REFERENCES medical_records(id),
    FOREIGN KEY (patient_id) REFERENCES patients(id),
    FOREIGN KEY (doctor_id) REFERENCES doctors(id),
    FOREIGN KEY (pharmacist_id) REFERENCES nurses(id),
    CHECK (status != 'dispensed' OR dispensed_at IS NOT NULL),
    CHECK (dispensed_at IS NULL OR dispensed_at >= prescribed_at)
);

CREATE TABLE prescription_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prescription_id INTEGER NOT NULL,
    medicine_name TEXT NOT NULL,
    specification TEXT NOT NULL,
    dosage TEXT NOT NULL,
    frequency TEXT NOT NULL CHECK (frequency IN ('QD', 'BID', 'TID', 'QID', 'Q4H', 'Q6H', 'Q8H', 'PRN')),
    duration_days INTEGER NOT NULL CHECK (duration_days > 0 AND duration_days <= 90),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit TEXT NOT NULL,
    is_controlled INTEGER NOT NULL DEFAULT 0 CHECK (is_controlled IN (0, 1)),
    notes TEXT,
    FOREIGN KEY (prescription_id) REFERENCES prescriptions(id) ON DELETE CASCADE,
    CHECK (quantity <= 1000)
);

CREATE TABLE admissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admission_no TEXT NOT NULL UNIQUE,
    patient_id INTEGER NOT NULL,
    doctor_id INTEGER NOT NULL,
    department_id INTEGER NOT NULL,
    bed_no TEXT NOT NULL,
    admission_type TEXT NOT NULL CHECK (admission_type IN ('emergency', 'scheduled', 'transfer', 'observation')),
    admission_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expected_discharge DATE,
    actual_discharge DATETIME,
    discharge_summary TEXT,
    deposit_amount REAL NOT NULL DEFAULT 0.0 CHECK (deposit_amount >= 0.0),
    status TEXT NOT NULL DEFAULT 'admitted' CHECK (status IN ('admitted', 'discharged', 'transferred')),
    FOREIGN KEY (patient_id) REFERENCES patients(id),
    FOREIGN KEY (doctor_id) REFERENCES doctors(id),
    FOREIGN KEY (department_id) REFERENCES departments(id),
    CHECK (actual_discharge IS NULL OR actual_discharge >= admission_date),
    CHECK (status != 'discharged' OR actual_discharge IS NOT NULL)
);

CREATE TABLE lab_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_no TEXT NOT NULL UNIQUE,
    patient_id INTEGER NOT NULL,
    doctor_id INTEGER NOT NULL,
    record_id INTEGER,
    test_type TEXT NOT NULL CHECK (test_type IN ('blood', 'urine', 'stool', 'imaging', 'biopsy', 'cardiac', 'other')),
    test_name TEXT NOT NULL,
    ordered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    collected_at DATETIME,
    resulted_at DATETIME,
    result_value TEXT,
    result_unit TEXT,
    reference_range TEXT,
    is_abnormal INTEGER CHECK (is_abnormal IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'ordered' CHECK (status IN ('ordered', 'collected', 'resulted', 'cancelled')),
    FOREIGN KEY (patient_id) REFERENCES patients(id),
    FOREIGN KEY (doctor_id) REFERENCES doctors(id),
    FOREIGN KEY (record_id) REFERENCES medical_records(id),
    CHECK (status != 'collected' OR collected_at IS NOT NULL),
    CHECK (status != 'resulted' OR resulted_at IS NOT NULL),
    CHECK (collected_at IS NULL OR collected_at >= ordered_at),
    CHECK (resulted_at IS NULL OR resulted_at >= collected_at)
);

CREATE TABLE billing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_no TEXT NOT NULL UNIQUE,
    patient_id INTEGER NOT NULL,
    admission_id INTEGER,
    appointment_id INTEGER,
    item_type TEXT NOT NULL CHECK (item_type IN ('registration', 'consultation', 'medication', 'lab_test', 'procedure', 'bed_charge', 'other')),
    description TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price REAL NOT NULL CHECK (unit_price >= 0.0),
    total_price REAL NOT NULL CHECK (total_price >= 0.0),
    insurance_covered REAL NOT NULL DEFAULT 0.0 CHECK (insurance_covered >= 0.0),
    patient_paid REAL NOT NULL DEFAULT 0.0 CHECK (patient_paid >= 0.0),
    status TEXT NOT NULL DEFAULT 'unpaid' CHECK (status IN ('unpaid', 'paid', 'refunded', 'written_off')),
    paid_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id),
    FOREIGN KEY (admission_id) REFERENCES admissions(id),
    FOREIGN KEY (appointment_id) REFERENCES appointments(id),
    CHECK (total_price = unit_price * quantity),
    CHECK (insurance_covered + patient_paid <= total_price),
    CHECK (status != 'paid' OR paid_at IS NOT NULL)
);
