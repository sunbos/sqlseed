-- Round 6: Banking Domain (12 tables)
-- Compatible: SQLite + PostgreSQL
-- Exercises: Pattern 29 (3-col arithmetic), Pattern 30 (conditional NULL),
--             Pattern 33 (conditional arithmetic by type), inequality CHECK,
--             self-referencing FK, compound UNIQUE, date ordering
-- Note: SQLite enables FK via PRAGMA foreign_keys=ON at connection time.
--       PostgreSQL enables FK by default. AUTOINCREMENT is SQLite syntax;
--       PG equivalent: GENERATED ALWAYS AS IDENTITY.

CREATE TABLE branches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    phone TEXT,
    manager_id INTEGER,
    region TEXT NOT NULL CHECK (region IN ('north', 'south', 'east', 'west', 'central')),
    opened_at DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed', 'merged')),
    FOREIGN KEY (manager_id) REFERENCES employees(id),
    CHECK (phone IS NULL OR LENGTH(phone) >= 10)
);

CREATE TABLE employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    emp_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    branch_id INTEGER NOT NULL,
    manager_id INTEGER,
    position TEXT NOT NULL CHECK (position IN ('teller', 'supervisor', 'manager', 'officer', 'clerk')),
    salary REAL NOT NULL CHECK (salary > 0),
    hire_date DATE NOT NULL,
    termination_date DATE,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'terminated', 'on_leave')),
    FOREIGN KEY (branch_id) REFERENCES branches(id),
    FOREIGN KEY (manager_id) REFERENCES employees(id),
    CHECK (termination_date IS NULL OR termination_date >= hire_date)
);

CREATE TABLE customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    id_card_no TEXT NOT NULL UNIQUE,
    phone TEXT NOT NULL,
    email TEXT,
    birth_date DATE,
    gender TEXT CHECK (gender IN ('male', 'female')),
    occupation TEXT,
    annual_income REAL CHECK (annual_income IS NULL OR annual_income >= 0),
    credit_score INTEGER CHECK (credit_score IS NULL OR (credit_score >= 300 AND credit_score <= 850)),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'frozen', 'closed')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (LENGTH(phone) >= 10)
);

CREATE TABLE accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_no TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL,
    branch_id INTEGER NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('savings', 'checking', 'credit', 'fixed_deposit')),
    currency TEXT NOT NULL DEFAULT 'CNY' CHECK (currency IN ('CNY', 'USD', 'EUR', 'HKD')),
    balance REAL NOT NULL DEFAULT 0.0 CHECK (balance >= 0.0 OR account_type = 'credit'),
    available_balance REAL NOT NULL DEFAULT 0.0,
    overdraft_limit REAL NOT NULL DEFAULT 0.0 CHECK (overdraft_limit >= 0.0),
    interest_rate REAL NOT NULL DEFAULT 0.0 CHECK (interest_rate >= 0.0 AND interest_rate <= 0.5),
    opened_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at DATETIME,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'frozen', 'closed')),
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (branch_id) REFERENCES branches(id),
    CHECK (closed_at IS NULL OR closed_at >= opened_at),
    CHECK (available_balance <= balance + overdraft_limit),
    CHECK (account_type != 'savings' OR overdraft_limit = 0.0)
);

CREATE TABLE cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_no TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    card_type TEXT NOT NULL CHECK (card_type IN ('debit', 'credit', 'prepaid')),
    card_network TEXT NOT NULL CHECK (card_network IN ('visa', 'mastercard', 'unionpay', 'amex')),
    credit_limit REAL NOT NULL DEFAULT 0.0 CHECK (credit_limit >= 0.0),
    available_credit REAL NOT NULL DEFAULT 0.0 CHECK (available_credit >= 0.0),
    cvv TEXT NOT NULL,
    pin_hash TEXT NOT NULL,
    issued_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expired_at DATE NOT NULL,
    activated_at DATETIME,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'blocked', 'expired')),
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (account_id) REFERENCES accounts(id),
    CHECK (expired_at > DATE(issued_at)),
    CHECK (status != 'active' OR activated_at IS NOT NULL),
    CHECK (card_type != 'credit' OR credit_limit > 0),
    CHECK (available_credit <= credit_limit)
);

CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_no TEXT NOT NULL UNIQUE,
    account_id INTEGER NOT NULL,
    card_id INTEGER,
    txn_type TEXT NOT NULL CHECK (txn_type IN ('deposit', 'withdrawal', 'transfer_in', 'transfer_out', 'payment', 'fee', 'interest')),
    amount REAL NOT NULL CHECK (amount > 0.0),
    balance_after REAL NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    channel TEXT NOT NULL CHECK (channel IN ('atm', 'counter', 'online', 'mobile', 'pos')),
    counterparty_account TEXT,
    description TEXT,
    txn_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('pending', 'completed', 'failed', 'reversed')),
    FOREIGN KEY (account_id) REFERENCES accounts(id),
    FOREIGN KEY (card_id) REFERENCES cards(id),
    CHECK (txn_type != 'withdrawal' OR direction = 'out'),
    CHECK (txn_type != 'deposit' OR direction = 'in'),
    CHECK (txn_type != 'fee' OR direction = 'out'),
    CHECK (txn_type != 'interest' OR direction = 'in')
);

CREATE TABLE transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transfer_no TEXT NOT NULL UNIQUE,
    debit_account_id INTEGER NOT NULL,
    credit_account_id INTEGER NOT NULL,
    amount REAL NOT NULL CHECK (amount > 0.0),
    fee REAL NOT NULL DEFAULT 0.0 CHECK (fee >= 0.0),
    transfer_type TEXT NOT NULL CHECK (transfer_type IN ('internal', 'external', 'cross_border')),
    reference TEXT,
    initiated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'failed', 'cancelled')),
    FOREIGN KEY (debit_account_id) REFERENCES accounts(id),
    FOREIGN KEY (credit_account_id) REFERENCES accounts(id),
    CHECK (debit_account_id != credit_account_id),
    CHECK (completed_at IS NULL OR completed_at >= initiated_at),
    CHECK (transfer_type != 'cross_border' OR fee > 0.0)
);

CREATE TABLE loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_no TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    loan_type TEXT NOT NULL CHECK (loan_type IN ('mortgage', 'auto', 'personal', 'business', 'education')),
    principal REAL NOT NULL CHECK (principal > 0.0),
    interest_rate REAL NOT NULL CHECK (interest_rate > 0.0 AND interest_rate <= 0.5),
    term_months INTEGER NOT NULL CHECK (term_months > 0 AND term_months <= 360),
    monthly_payment REAL NOT NULL CHECK (monthly_payment > 0.0),
    total_payable REAL NOT NULL CHECK (total_payable > 0.0),
    disbursed_at DATETIME NOT NULL,
    maturity_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('pending', 'active', 'paid_off', 'defaulted', 'rejected')),
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (account_id) REFERENCES accounts(id),
    CHECK (maturity_date > DATE(disbursed_at)),
    CHECK (total_payable = principal + principal * interest_rate * term_months / 12.0)
);

CREATE TABLE loan_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_no TEXT NOT NULL UNIQUE,
    loan_id INTEGER NOT NULL,
    installment_no INTEGER NOT NULL CHECK (installment_no > 0),
    principal_amount REAL NOT NULL CHECK (principal_amount >= 0.0),
    interest_amount REAL NOT NULL CHECK (interest_amount >= 0.0),
    penalty_amount REAL NOT NULL DEFAULT 0.0 CHECK (penalty_amount >= 0.0),
    total_amount REAL NOT NULL CHECK (total_amount > 0.0),
    due_date DATE NOT NULL,
    paid_at DATETIME,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'paid', 'overdue', 'partial')),
    FOREIGN KEY (loan_id) REFERENCES loans(id),
    CHECK (total_amount = principal_amount + interest_amount + penalty_amount),
    CHECK (paid_at IS NULL OR DATE(paid_at) >= due_date),
    CHECK (status != 'paid' OR paid_at IS NOT NULL)
);

CREATE TABLE deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deposit_no TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    deposit_type TEXT NOT NULL CHECK (deposit_type IN ('fixed', 'notice', 'certificate')),
    principal REAL NOT NULL CHECK (principal > 0.0),
    interest_rate REAL NOT NULL CHECK (interest_rate >= 0.0 AND interest_rate <= 0.5),
    term_months INTEGER NOT NULL CHECK (term_months > 0),
    expected_interest REAL NOT NULL CHECK (expected_interest >= 0.0),
    maturity_amount REAL NOT NULL CHECK (maturity_amount > 0.0),
    start_date DATE NOT NULL,
    maturity_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'matured', 'withdrawn')),
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (account_id) REFERENCES accounts(id),
    CHECK (maturity_date > start_date),
    CHECK (maturity_amount = principal + expected_interest),
    CHECK (expected_interest = principal * interest_rate * term_months / 12.0)
);

CREATE TABLE exchange_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    base_currency TEXT NOT NULL CHECK (base_currency IN ('CNY', 'USD', 'EUR', 'HKD')),
    quote_currency TEXT NOT NULL CHECK (quote_currency IN ('CNY', 'USD', 'EUR', 'HKD')),
    rate REAL NOT NULL CHECK (rate > 0.0),
    buy_rate REAL NOT NULL CHECK (buy_rate > 0.0),
    sell_rate REAL NOT NULL CHECK (sell_rate > 0.0),
    effective_at DATETIME NOT NULL,
    expired_at DATETIME,
    CHECK (base_currency != quote_currency),
    CHECK (buy_rate <= rate),
    CHECK (sell_rate >= rate),
    CHECK (expired_at IS NULL OR expired_at > effective_at)
);

CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_no TEXT NOT NULL UNIQUE,
    employee_id INTEGER,
    action TEXT NOT NULL CHECK (action IN ('login', 'logout', 'create', 'update', 'delete', 'approve', 'reject')),
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    old_value TEXT,
    new_value TEXT,
    ip_address TEXT,
    user_agent TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (employee_id) REFERENCES employees(id),
    CHECK (ip_address IS NULL OR ip_address LIKE '%.%.%.%')
);
