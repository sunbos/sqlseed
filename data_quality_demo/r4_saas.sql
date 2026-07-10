-- Round 4: SaaS Multi-Tenant Platform (13 tables)
-- Compatible: SQLite + PostgreSQL
-- Exercises: Org hierarchy, tenant isolation, subscription billing cycle,
--             RBAC, API key rotation, usage metering, conditional NULL,
--             cross-column date/pricing constraints
-- Note: SQLite enables FK via PRAGMA foreign_keys=ON at connection time.
--       PostgreSQL enables FK by default. AUTOINCREMENT is SQLite syntax;
--       PG equivalent: GENERATED ALWAYS AS IDENTITY.

CREATE TABLE organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    parent_id INTEGER,
    org_type TEXT NOT NULL CHECK (org_type IN ('root', 'division', 'team', 'project')),
    industry TEXT CHECK (industry IN ('tech', 'finance', 'healthcare', 'education', 'retail', 'manufacturing', 'other')),
    country_code TEXT NOT NULL DEFAULT 'CN' CHECK (LENGTH(country_code) = 2),
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    metadata TEXT,
    max_users INTEGER NOT NULL DEFAULT 50 CHECK (max_users > 0 AND max_users <= 100000),
    max_storage_gb INTEGER NOT NULL DEFAULT 100 CHECK (max_storage_gb > 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'terminated')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    terminated_at DATETIME,
    FOREIGN KEY (parent_id) REFERENCES organizations(id),
    CHECK (org_type != 'root' OR parent_id IS NULL),
    CHECK (org_type = 'root' OR parent_id IS NOT NULL),
    CHECK (status != 'terminated' OR terminated_at IS NOT NULL),
    CHECK (terminated_at IS NULL OR terminated_at >= created_at)
);

CREATE TABLE plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    tier TEXT NOT NULL CHECK (tier IN ('free', 'starter', 'pro', 'business', 'enterprise')),
    base_price_monthly REAL NOT NULL CHECK (base_price_monthly >= 0.0),
    base_price_yearly REAL NOT NULL CHECK (base_price_yearly >= 0.0),
    seat_price_monthly REAL NOT NULL DEFAULT 0.0 CHECK (seat_price_monthly >= 0.0),
    storage_gb_included INTEGER NOT NULL CHECK (storage_gb_included > 0),
    api_calls_monthly INTEGER NOT NULL CHECK (api_calls_monthly > 0),
    max_seats INTEGER CHECK (max_seats IS NULL OR max_seats > 0),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    introduced_at DATE NOT NULL,
    deprecated_at DATE,
    CHECK (base_price_yearly <= base_price_monthly * 12),
    CHECK (base_price_yearly >= base_price_monthly * 10),
    CHECK (deprecated_at IS NULL OR deprecated_at > introduced_at),
    CHECK (tier != 'free' OR base_price_monthly = 0.0)
);

CREATE TABLE tenants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_code TEXT NOT NULL UNIQUE,
    tenant_uuid TEXT NOT NULL UNIQUE CHECK (LENGTH(tenant_uuid) = 36),
    org_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    plan_id INTEGER,
    region TEXT NOT NULL CHECK (region IN ('cn-north', 'cn-east', 'cn-south', 'us-east', 'eu-west', 'ap-southeast')),
    database_name TEXT NOT NULL UNIQUE,
    schema_prefix TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'provisioning' CHECK (status IN ('provisioning', 'active', 'suspended', 'migrating', 'deleted')),
    trial_ends_at DATETIME,
    suspended_at DATETIME,
    deleted_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (org_id) REFERENCES organizations(id),
    FOREIGN KEY (plan_id) REFERENCES plans(id),
    CHECK (status != 'suspended' OR suspended_at IS NOT NULL),
    CHECK (status != 'deleted' OR deleted_at IS NOT NULL),
    CHECK (suspended_at IS NULL OR suspended_at >= created_at),
    CHECK (deleted_at IS NULL OR deleted_at >= created_at)
);

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_code TEXT NOT NULL UNIQUE,
    tenant_id INTEGER NOT NULL,
    org_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    username TEXT NOT NULL,
    display_name TEXT NOT NULL,
    phone TEXT,
    avatar_url TEXT,
    locale TEXT NOT NULL DEFAULT 'zh-CN',
    mfa_enabled INTEGER NOT NULL DEFAULT 0 CHECK (mfa_enabled IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'invited' CHECK (status IN ('invited', 'active', 'suspended', 'deleted')),
    last_login_at DATETIME,
    password_changed_at DATETIME,
    invited_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    activated_at DATETIME,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (org_id) REFERENCES organizations(id),
    CHECK (status != 'active' OR activated_at IS NOT NULL),
    CHECK (status != 'active' OR last_login_at IS NULL OR last_login_at >= activated_at),
    CHECK (phone IS NULL OR LENGTH(phone) >= 7),
    CHECK (LOWER(email) = email),
    CHECK (password_changed_at IS NULL OR password_changed_at >= invited_at),
    CHECK (status = 'deleted' OR last_login_at IS NULL OR last_login_at >= activated_at)
);

CREATE TABLE roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_code TEXT NOT NULL UNIQUE,
    tenant_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    is_system INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0, 1)),
    priority INTEGER NOT NULL DEFAULT 100 CHECK (priority >= 0 AND priority <= 1000),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deprecated')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CHECK (is_system != 1 OR priority < 100)
);

CREATE TABLE permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    perm_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    resource TEXT NOT NULL CHECK (resource IN ('users', 'roles', 'billing', 'api_keys', 'audit_logs', 'tenants', 'settings', 'data')),
    action TEXT NOT NULL CHECK (action IN ('read', 'write', 'delete', 'admin', 'export', 'import')),
    scope TEXT NOT NULL CHECK (scope IN ('self', 'tenant', 'org', 'global')),
    description TEXT,
    is_dangerous INTEGER NOT NULL DEFAULT 0 CHECK (is_dangerous IN (0, 1)),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (scope != 'global' OR action = 'admin' OR action = 'read')
);

CREATE TABLE role_permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id INTEGER NOT NULL,
    permission_id INTEGER NOT NULL,
    granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    granted_by INTEGER NOT NULL,
    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
    FOREIGN KEY (permission_id) REFERENCES permissions(id),
    FOREIGN KEY (granted_by) REFERENCES users(id),
    UNIQUE (role_id, permission_id)
);

CREATE TABLE user_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    assigned_by INTEGER,
    expires_at DATETIME,
    revoked_at DATETIME,
    revoke_reason TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (role_id) REFERENCES roles(id),
    FOREIGN KEY (assigned_by) REFERENCES users(id),
    UNIQUE (user_id, role_id),
    CHECK (expires_at IS NULL OR expires_at > assigned_at),
    CHECK (revoked_at IS NULL OR revoked_at >= assigned_at),
    CHECK (revoked_at IS NULL OR expires_at IS NULL OR revoked_at <= expires_at)
);

CREATE TABLE subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_no TEXT NOT NULL UNIQUE,
    tenant_id INTEGER NOT NULL,
    plan_id INTEGER NOT NULL,
    billing_cycle TEXT NOT NULL CHECK (billing_cycle IN ('monthly', 'yearly')),
    seat_count INTEGER NOT NULL DEFAULT 1 CHECK (seat_count > 0),
    base_amount REAL NOT NULL CHECK (base_amount >= 0.0),
    seat_amount REAL NOT NULL DEFAULT 0.0 CHECK (seat_amount >= 0.0),
    discount_rate REAL NOT NULL DEFAULT 0.0 CHECK (discount_rate >= 0.0 AND discount_rate <= 1.0),
    total_amount REAL NOT NULL CHECK (total_amount >= 0.0),
    status TEXT NOT NULL DEFAULT 'trialing' CHECK (status IN ('trialing', 'active', 'past_due', 'canceled', 'expired')),
    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    current_period_start DATETIME NOT NULL,
    current_period_end DATETIME NOT NULL,
    canceled_at DATETIME,
    ended_at DATETIME,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
    FOREIGN KEY (plan_id) REFERENCES plans(id),
    CHECK (current_period_end > current_period_start),
    CHECK (total_amount = (base_amount + seat_amount) * (1.0 - discount_rate)),
    CHECK (status != 'canceled' OR canceled_at IS NOT NULL),
    CHECK (status != 'expired' OR ended_at IS NOT NULL),
    CHECK (canceled_at IS NULL OR canceled_at >= started_at),
    CHECK (ended_at IS NULL OR ended_at >= current_period_end),
    CHECK (status != 'trialing' OR discount_rate = 0.0),
    CHECK (status != 'suspended' OR seat_count < 1000)
);

CREATE TABLE invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_no TEXT NOT NULL UNIQUE,
    tenant_id INTEGER NOT NULL,
    subscription_id INTEGER NOT NULL,
    period_start DATETIME NOT NULL,
    period_end DATETIME NOT NULL,
    subtotal REAL NOT NULL CHECK (subtotal >= 0.0),
    discount_amount REAL NOT NULL DEFAULT 0.0 CHECK (discount_amount >= 0.0),
    tax_amount REAL NOT NULL DEFAULT 0.0 CHECK (tax_amount >= 0.0),
    total_amount REAL NOT NULL CHECK (total_amount >= 0.0),
    paid_amount REAL NOT NULL DEFAULT 0.0 CHECK (paid_amount >= 0.0),
    currency TEXT NOT NULL DEFAULT 'CNY' CHECK (currency IN ('CNY', 'USD', 'EUR', 'GBP', 'JPY')),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'sent', 'paid', 'partial', 'overdue', 'void')),
    issued_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    due_date DATE NOT NULL,
    paid_at DATETIME,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
    FOREIGN KEY (subscription_id) REFERENCES subscriptions(id),
    CHECK (period_end > period_start),
    CHECK (total_amount = subtotal - discount_amount + tax_amount),
    CHECK (paid_amount <= total_amount),
    CHECK (discount_amount <= subtotal),
    CHECK (status != 'paid' OR paid_at IS NOT NULL),
    CHECK (status != 'paid' OR paid_amount >= total_amount),
    CHECK (paid_at IS NULL OR paid_at >= issued_at),
    CHECK (due_date >= DATE(period_start))
);

CREATE TABLE api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id TEXT NOT NULL UNIQUE,
    key_hash TEXT NOT NULL UNIQUE,
    tenant_id INTEGER NOT NULL,
    owner_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    scopes TEXT NOT NULL,
    rate_limit_per_min INTEGER NOT NULL DEFAULT 60 CHECK (rate_limit_per_min > 0 AND rate_limit_per_min <= 10000),
    rate_limit_per_day INTEGER NOT NULL DEFAULT 10000 CHECK (rate_limit_per_day > 0),
    last_used_at DATETIME,
    last_used_ip TEXT,
    total_requests INTEGER NOT NULL DEFAULT 0 CHECK (total_requests >= 0),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME,
    revoked_at DATETIME,
    revoke_reason TEXT,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id) REFERENCES users(id),
    CHECK (expires_at IS NULL OR expires_at > created_at),
    CHECK (revoked_at IS NULL OR revoked_at >= created_at),
    CHECK (revoked_at IS NULL OR expires_at IS NULL OR revoked_at <= expires_at),
    CHECK (last_used_at IS NULL OR last_used_at >= created_at),
    CHECK (rate_limit_per_day >= rate_limit_per_min)
);

CREATE TABLE usage_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_no TEXT NOT NULL UNIQUE,
    tenant_id INTEGER NOT NULL,
    metric_type TEXT NOT NULL CHECK (metric_type IN ('api_calls', 'storage_gb', 'seats', 'bandwidth_gb', 'compute_hours', 'documents')),
    metric_value REAL NOT NULL CHECK (metric_value >= 0.0),
    period_start DATETIME NOT NULL,
    period_end DATETIME NOT NULL,
    unit TEXT NOT NULL CHECK (unit IN ('count', 'gb', 'hours', 'bytes', 'seconds')),
    quota_limit REAL CHECK (quota_limit IS NULL OR quota_limit >= 0.0),
    overage_amount REAL NOT NULL DEFAULT 0.0 CHECK (overage_amount >= 0.0),
    overage_charge REAL NOT NULL DEFAULT 0.0 CHECK (overage_charge >= 0.0),
    recorded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CHECK (period_end > period_start),
    CHECK (quota_limit IS NULL OR metric_value <= quota_limit + overage_amount),
    CHECK (overage_charge = 0.0 OR overage_amount > 0.0)
);

CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_no TEXT NOT NULL UNIQUE,
    tenant_id INTEGER NOT NULL,
    actor_id INTEGER,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'api_key', 'system', 'webhook')),
    action TEXT NOT NULL CHECK (action IN ('create', 'update', 'delete', 'login', 'logout', 'export', 'import', 'grant', 'revoke', 'config_change')),
    resource_type TEXT NOT NULL CHECK (resource_type IN ('user', 'role', 'tenant', 'subscription', 'api_key', 'invoice', 'data', 'setting')),
    resource_id INTEGER,
    ip_address TEXT,
    user_agent TEXT,
    request_id TEXT,
    old_values TEXT,
    new_values TEXT,
    severity TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('debug', 'info', 'warning', 'critical')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
    FOREIGN KEY (actor_id) REFERENCES users(id),
    CHECK (actor_type != 'user' OR actor_id IS NOT NULL),
    CHECK (action != 'update' OR old_values IS NOT NULL OR new_values IS NOT NULL),
    CHECK (ip_address IS NULL OR ip_address LIKE '%.%.%.%' OR ip_address LIKE '%:%')
);
