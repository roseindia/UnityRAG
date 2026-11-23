-- =============================================================================
-- 04  Identity and access control (tenant scope)
-- Spec refs: 6.1 (FR-001..FR-011), 6.11 (FR-163..FR-165), 10.2.1, 11.
-- Every tenant-owned table carries tenant_id NOT NULL and a composite
-- (tenant_id, <pk>) unique key so children reference parents with
-- tenant-consistent composite foreign keys: a row can never point at a parent
-- in another tenant (extension 2.2).
-- =============================================================================
CREATE TABLE IF NOT EXISTS iam.departments (
  tenant_id            uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  department_id        uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  code                 text NOT NULL CHECK (code ~ '^[A-Za-z0-9_-]{2,40}$'),
  name                 text NOT NULL,
  description          text,
  parent_department_id uuid,
  status               text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, department_id),
  UNIQUE (tenant_id, code),
  FOREIGN KEY (tenant_id, parent_department_id) REFERENCES iam.departments (tenant_id, department_id)
);

CREATE TABLE IF NOT EXISTS iam.users (
  tenant_id         uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  user_id           uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  account_id        uuid NOT NULL REFERENCES iam.user_accounts(account_id) ON DELETE RESTRICT,
  email             citext NOT NULL,
  display_name      text NOT NULL,
  user_type         text NOT NULL DEFAULT 'employee' CHECK (user_type IN ('employee', 'broker', 'agent', 'service')),
  department_id     uuid,
  business_unit     text,
  country           text,
  lines_of_business text[] NOT NULL DEFAULT '{}',   -- '*' = all lines
  jurisdictions     text[] NOT NULL DEFAULT '{}',   -- '*' = all jurisdictions
  clearance_rank    smallint NOT NULL DEFAULT 1 CHECK (clearance_rank BETWEEN 0 AND 3),
  status            text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
  last_active_at    timestamptz,
  created_by        uuid,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, user_id),
  UNIQUE (tenant_id, account_id),
  UNIQUE (tenant_id, email),
  FOREIGN KEY (tenant_id, department_id) REFERENCES iam.departments (tenant_id, department_id)
);

-- User-to-tenant membership: the trust anchor for tenant resolution.
CREATE TABLE IF NOT EXISTS iam.tenant_memberships (
  membership_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  account_id    uuid NOT NULL REFERENCES iam.user_accounts(account_id) ON DELETE RESTRICT,
  user_id       uuid NOT NULL,
  status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'revoked')),
  is_default    boolean NOT NULL DEFAULT false,
  created_by    uuid,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, account_id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES iam.users (tenant_id, user_id)
);

CREATE TABLE IF NOT EXISTS iam.teams (
  tenant_id     uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  team_id       uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  department_id uuid NOT NULL,
  name          text NOT NULL,
  description   text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, team_id),
  UNIQUE (tenant_id, department_id, name),
  FOREIGN KEY (tenant_id, department_id) REFERENCES iam.departments (tenant_id, department_id)
);

CREATE TABLE IF NOT EXISTS iam.team_members (
  tenant_id uuid NOT NULL,
  team_id   uuid NOT NULL,
  user_id   uuid NOT NULL,
  added_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (team_id, user_id),
  FOREIGN KEY (tenant_id, team_id) REFERENCES iam.teams (tenant_id, team_id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, user_id) REFERENCES iam.users (tenant_id, user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS iam.user_groups (
  tenant_id   uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  group_id    uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  name        text NOT NULL,
  description text,
  source      text NOT NULL DEFAULT 'platform' CHECK (source IN ('platform', 'idp')),
  external_id text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, group_id),
  UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS iam.user_group_members (
  tenant_id  uuid NOT NULL,
  group_id   uuid NOT NULL,
  user_id    uuid NOT NULL,
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to   timestamptz,
  added_by   uuid,
  PRIMARY KEY (group_id, user_id),
  FOREIGN KEY (tenant_id, group_id) REFERENCES iam.user_groups (tenant_id, group_id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, user_id)  REFERENCES iam.users (tenant_id, user_id) ON DELETE CASCADE,
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);

-- Global permission catalogue: reference data, identical for every tenant,
-- contains no tenant information => no RLS (documented in database design).
CREATE TABLE IF NOT EXISTS iam.permissions (
  permission_code text PRIMARY KEY CHECK (permission_code ~ '^[a-z_]+(\.[a-z_]+)+$'),
  description     text NOT NULL,
  category        text NOT NULL,
  is_admin        boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS iam.roles (
  tenant_id      uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  role_id        uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  code           text NOT NULL CHECK (code ~ '^[a-z0-9_]{2,60}$'),
  name           text NOT NULL,
  description    text,
  is_system      boolean NOT NULL DEFAULT false,   -- protected from modification
  is_admin       boolean NOT NULL DEFAULT false,
  conflicts_with text[] NOT NULL DEFAULT '{}',     -- segregation of duties (FR-165)
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, role_id),
  UNIQUE (tenant_id, code)
);

CREATE TABLE IF NOT EXISTS iam.role_permissions (
  tenant_id       uuid NOT NULL,
  role_id         uuid NOT NULL,
  permission_code text NOT NULL REFERENCES iam.permissions(permission_code) ON DELETE CASCADE,
  PRIMARY KEY (role_id, permission_code),
  FOREIGN KEY (tenant_id, role_id) REFERENCES iam.roles (tenant_id, role_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS iam.user_roles (
  tenant_id  uuid NOT NULL,
  user_id    uuid NOT NULL,
  role_id    uuid NOT NULL,
  scope      jsonb NOT NULL DEFAULT '{}'::jsonb,
  granted_by uuid,
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to   timestamptz,                         -- role expiry (FR-007)
  granted_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, role_id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES iam.users (tenant_id, user_id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, role_id) REFERENCES iam.roles (tenant_id, role_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS iam.user_attributes (
  tenant_id uuid NOT NULL,
  user_id   uuid NOT NULL,
  key       text NOT NULL,
  value     text NOT NULL,
  PRIMARY KEY (user_id, key, value),
  FOREIGN KEY (tenant_id, user_id) REFERENCES iam.users (tenant_id, user_id) ON DELETE CASCADE
);

-- Sessions: one per login per active tenant.  Refresh tokens rotate within a
-- family; reuse of a rotated token revokes the whole family (token theft).
CREATE TABLE IF NOT EXISTS iam.sessions (
  session_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id       uuid NOT NULL REFERENCES iam.user_accounts(account_id) ON DELETE CASCADE,
  tenant_id        uuid REFERENCES platform.tenants(tenant_id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  last_seen_at     timestamptz NOT NULL DEFAULT now(),
  absolute_expires_at timestamptz NOT NULL,
  mfa_verified_at  timestamptz,
  auth_method      text NOT NULL DEFAULT 'password',
  ip               inet,
  user_agent       text,
  revoked_at       timestamptz,
  revoked_reason   text
);

CREATE TABLE IF NOT EXISTS iam.refresh_tokens (
  token_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id  uuid NOT NULL REFERENCES iam.sessions(session_id) ON DELETE CASCADE,
  token_hash  text NOT NULL UNIQUE,     -- SHA-256 of the opaque token; token itself never stored
  issued_at   timestamptz NOT NULL DEFAULT now(),
  expires_at  timestamptz NOT NULL,
  used_at     timestamptz,
  revoked_at  timestamptz
);

CREATE TABLE IF NOT EXISTS iam.login_events (
  event_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id  uuid REFERENCES iam.user_accounts(account_id) ON DELETE SET NULL,
  tenant_id   uuid,
  email_hash  text,
  success     boolean NOT NULL,
  reason      text,
  auth_method text,
  ip          inet,
  user_agent  text,
  occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS iam.password_reset_tokens (
  token_hash text PRIMARY KEY,
  account_id uuid NOT NULL REFERENCES iam.user_accounts(account_id) ON DELETE CASCADE,
  requested_by uuid,
  expires_at timestamptz NOT NULL,
  used_at    timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_users_touch ON iam.users;
CREATE TRIGGER trg_users_touch BEFORE UPDATE ON iam.users FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
DROP TRIGGER IF EXISTS trg_roles_touch ON iam.roles;
CREATE TRIGGER trg_roles_touch BEFORE UPDATE ON iam.roles FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
DROP TRIGGER IF EXISTS trg_departments_touch ON iam.departments;
CREATE TRIGGER trg_departments_touch BEFORE UPDATE ON iam.departments FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
DROP TRIGGER IF EXISTS trg_memberships_touch ON iam.tenant_memberships;
CREATE TRIGGER trg_memberships_touch BEFORE UPDATE ON iam.tenant_memberships FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();

-- Segregation-of-duties guard: a user may not hold two roles that conflict.
CREATE OR REPLACE FUNCTION iam.enforce_role_sod() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE conflict text;
BEGIN
  SELECT r2.code INTO conflict
    FROM iam.roles r_new
    JOIN iam.user_roles ur ON ur.user_id = NEW.user_id AND ur.role_id <> NEW.role_id
                          AND (ur.valid_to IS NULL OR ur.valid_to > now())
    JOIN iam.roles r2 ON r2.role_id = ur.role_id
   WHERE r_new.role_id = NEW.role_id
     AND (r2.code = ANY (r_new.conflicts_with) OR r_new.code = ANY (r2.conflicts_with))
   LIMIT 1;
  IF conflict IS NOT NULL THEN
    RAISE EXCEPTION 'segregation of duties violation: role conflicts with %', conflict
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_user_roles_sod ON iam.user_roles;
CREATE TRIGGER trg_user_roles_sod BEFORE INSERT OR UPDATE ON iam.user_roles
  FOR EACH ROW EXECUTE FUNCTION iam.enforce_role_sod();
