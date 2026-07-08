-- Round 7: Insurance Domain (12 tables)
-- Exercises: Pattern 36 (N-way conditional range with dual bounds),
--             Pattern 8e (col >= X AND col < other_col),
--             Pattern 28 (cross-column upper bound via min()),
--             IS NULL OR prefix stripping, multi-clause compound OR CHECK

PRAGMA foreign_keys = ON;

CREATE TABLE agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    manager_id INTEGER,
    hire_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'terminated')),
    commission_rate REAL NOT NULL CHECK (commission_rate >= 0.01 AND commission_rate <= 0.3),
    FOREIGN KEY (manager_id) REFERENCES agents(id)
);

CREATE TABLE customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_code TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    birth_date DATE,
    gender TEXT CHECK (gender IN ('male', 'female', 'other')),
    id_card_no TEXT NOT NULL UNIQUE,
    phone TEXT,
    email TEXT,
    address TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (phone IS NULL OR LENGTH(phone) = 11)
);

CREATE TABLE policies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_no TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL,
    agent_id INTEGER NOT NULL,
    policy_type TEXT NOT NULL CHECK (policy_type IN ('life', 'health', 'auto', 'property', 'term')),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'lapsed', 'cancelled', 'expired')),
    effective_date DATE NOT NULL,
    expiry_date DATE NOT NULL,
    term_years INTEGER NOT NULL CHECK (term_years > 0),
    coverage_amount REAL NOT NULL CHECK (coverage_amount >= 0.01),
    deductible REAL NOT NULL CHECK (deductible >= 0.0 AND deductible < coverage_amount),
    premium REAL NOT NULL CHECK (premium >= 0.01),
    payment_frequency TEXT NOT NULL DEFAULT 'annual' CHECK (payment_frequency IN ('monthly', 'quarterly', 'annual')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (agent_id) REFERENCES agents(id),
    CHECK (expiry_date > effective_date)
);

CREATE TABLE agent_commissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL,
    policy_id INTEGER NOT NULL,
    commission_no TEXT NOT NULL UNIQUE,
    premium_amount REAL NOT NULL CHECK (premium_amount >= 0.01),
    commission_rate REAL NOT NULL CHECK (commission_rate >= 0.01 AND commission_rate <= 0.3),
    commission_amount REAL NOT NULL CHECK (commission_amount >= 0.0),
    status TEXT NOT NULL DEFAULT 'accrued' CHECK (status IN ('accrued', 'paid', 'reversed')),
    paid_date DATE,
    FOREIGN KEY (agent_id) REFERENCES agents(id),
    FOREIGN KEY (policy_id) REFERENCES policies(id),
    CHECK (commission_amount = premium_amount * commission_rate)
);

CREATE TABLE claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_no TEXT NOT NULL UNIQUE,
    policy_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    claim_type TEXT NOT NULL CHECK (claim_type IN ('medical', 'accident', 'property_damage', 'death', 'theft')),
    status TEXT NOT NULL DEFAULT 'filed' CHECK (status IN ('filed', 'reviewed', 'approved', 'rejected', 'settled')),
    claim_amount REAL NOT NULL CHECK (claim_amount >= 0.01),
    approved_amount REAL,
    deductible_applied REAL NOT NULL DEFAULT 0.0 CHECK (deductible_applied >= 0.0),
    filed_date DATE NOT NULL,
    reviewed_date DATE,
    settled_date DATE,
    description TEXT,
    FOREIGN KEY (policy_id) REFERENCES policies(id),
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    CHECK (approved_amount IS NULL OR approved_amount <= claim_amount),
    CHECK (status != 'approved' OR approved_amount > 0.0),
    CHECK (reviewed_date IS NULL OR reviewed_date >= filed_date),
    CHECK (settled_date IS NULL OR settled_date >= reviewed_date)
);

CREATE TABLE claim_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id INTEGER NOT NULL,
    doc_type TEXT NOT NULL CHECK (doc_type IN ('medical_record', 'police_report', 'photo', 'invoice', 'witness_statement', 'other')),
    file_path TEXT NOT NULL,
    uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    verified INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    verified_by INTEGER,
    verified_at DATETIME,
    FOREIGN KEY (claim_id) REFERENCES claims(id) ON DELETE CASCADE,
    FOREIGN KEY (verified_by) REFERENCES agents(id),
    CHECK (verified != 1 OR verified_at IS NOT NULL)
);

CREATE TABLE claim_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id INTEGER NOT NULL,
    evaluator_id INTEGER NOT NULL,
    evaluation_date DATETIME NOT NULL,
    liability_percent REAL NOT NULL CHECK (liability_percent >= 0.0 AND liability_percent <= 1.0),
    recommended_amount REAL NOT NULL CHECK (recommended_amount >= 0.0),
    fraud_risk_score INTEGER NOT NULL CHECK (fraud_risk_score >= 1 AND fraud_risk_score <= 10),
    notes TEXT,
    FOREIGN KEY (claim_id) REFERENCES claims(id),
    FOREIGN KEY (evaluator_id) REFERENCES agents(id)
);

CREATE TABLE claim_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id INTEGER NOT NULL,
    payment_no TEXT NOT NULL UNIQUE,
    payee_name TEXT NOT NULL,
    amount REAL NOT NULL CHECK (amount >= 0.01),
    payment_date DATE NOT NULL,
    payment_method TEXT NOT NULL CHECK (payment_method IN ('cash', 'card', 'bank_transfer', 'check')),
    check_number TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'failed')),
    FOREIGN KEY (claim_id) REFERENCES claims(id),
    CHECK (payment_method != 'check' OR check_number IS NOT NULL)
);

CREATE TABLE policy_beneficiaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    relationship TEXT NOT NULL CHECK (relationship IN ('spouse', 'child', 'parent', 'sibling', 'other')),
    beneficiary_share REAL NOT NULL CHECK (beneficiary_share >= 0.01 AND beneficiary_share <= 1.0),
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
    FOREIGN KEY (policy_id) REFERENCES policies(id) ON DELETE CASCADE,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE policy_endorsements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_id INTEGER NOT NULL,
    endorsement_no TEXT NOT NULL UNIQUE,
    endorsement_type TEXT NOT NULL CHECK (endorsement_type IN ('coverage_increase', 'coverage_decrease', 'beneficiary_change', 'address_change', 'cancel')),
    effective_date DATE NOT NULL,
    approved_by INTEGER,
    approved_at DATETIME,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    description TEXT,
    FOREIGN KEY (policy_id) REFERENCES policies(id),
    FOREIGN KEY (approved_by) REFERENCES agents(id),
    CHECK (status != 'approved' OR approved_at IS NOT NULL)
);

CREATE TABLE policy_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_id INTEGER NOT NULL,
    payment_no TEXT NOT NULL UNIQUE,
    amount REAL NOT NULL CHECK (amount >= 0.01),
    payment_date DATE NOT NULL,
    payment_method TEXT NOT NULL CHECK (payment_method IN ('cash', 'card', 'bank_transfer', 'check')),
    check_number TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'failed', 'refunded')),
    FOREIGN KEY (policy_id) REFERENCES policies(id),
    CHECK (payment_method != 'check' OR check_number IS NOT NULL)
);

CREATE TABLE risk_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_id INTEGER NOT NULL,
    assessor_id INTEGER NOT NULL,
    assessment_date DATE NOT NULL,
    risk_category TEXT NOT NULL CHECK (risk_category IN ('low', 'medium', 'high', 'critical')),
    risk_score INTEGER NOT NULL,
    health_factor INTEGER,
    auto_factor INTEGER NOT NULL CHECK (auto_factor >= 1 AND auto_factor <= 10),
    property_factor INTEGER NOT NULL CHECK (property_factor >= 1 AND property_factor <= 10),
    notes TEXT,
    FOREIGN KEY (policy_id) REFERENCES policies(id),
    FOREIGN KEY (assessor_id) REFERENCES agents(id),
    CHECK (health_factor IS NULL OR (health_factor >= 1 AND health_factor <= 10)),
    CHECK (risk_category = 'low' AND risk_score >= 1 AND risk_score < 25
           OR risk_category = 'medium' AND risk_score >= 25 AND risk_score < 50
           OR risk_category = 'high' AND risk_score >= 50 AND risk_score < 75
           OR risk_category = 'critical' AND risk_score >= 75 AND risk_score <= 100)
);
