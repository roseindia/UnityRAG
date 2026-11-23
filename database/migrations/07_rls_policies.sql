-- =============================================================================
-- 07  Row-Level Security policies and privileges for groups 03-06
--     (chat, AI configuration, audit/analytics and evaluation tables get their
--      policies in their own migration files 09-12, using the same helpers).
--
-- Layering (extension 2.4):
--   1. RESTRICTIVE tenant policy on every tenant-owned table (tenant isolation;
--      user-facing modes additionally require an operational tenant).
--   2. PERMISSIVE policies per access mode / ownership / ACL.
--   3. RBAC/ABAC and final authorisation in the application services.
--
-- Access modes (app.current_access_mode, set server-side per transaction):
--   user                  normal tenant user
--   tenant_admin          tenant administration (metadata, identity, config) -
--                         NO document content access (spec SP-08)
--   auditor               tenant audit / reporting read
--   worker                background worker for exactly one tenant
--   platform              platform administration (platform tables only)
--   platform_provisioning platform admin acting on ONE tenant's identity and
--                         configuration tables (onboarding, tenant admins)
--   break_glass           time-limited, audited, read-only support access
-- Anything else (including no context) matches no permissive policy => no rows.
-- =============================================================================

-- ACL predicate shared by documents, chunks and embeddings (inlined by the
-- planner; array operators are GIN-indexable).  Spec 10.6 rules 6-7, FR-087,
-- FR-101..FR-104, FR-107.
CREATE OR REPLACE FUNCTION app.acl_visible(p_rank smallint, p_lob text, p_jurisdictions text[], p_lifecycle text,
                                           p_allow uuid[], p_deny uuid[]) RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE AS $$
  SELECT p_lifecycle IN ('published', 'superseded')
     AND p_rank <= app.current_max_class()
     AND (p_lob IS NULL OR p_lob = ANY (app.current_lobs()) OR '*' = ANY (app.current_lobs()))
     AND (cardinality(p_jurisdictions) = 0 OR p_jurisdictions && app.current_jurisdictions()
          OR '*' = ANY (app.current_jurisdictions()))
     AND p_allow && app.current_principals()
     AND NOT (p_deny && app.current_principals())
$$;

CREATE OR REPLACE FUNCTION app.break_glass_active() RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT app.current_access_mode() = 'break_glass'
     AND app.current_platform_role() IS NOT NULL
     AND EXISTS (SELECT 1 FROM platform.break_glass_grants g
                  WHERE g.account_id = app.current_account_id()
                    AND g.tenant_id = app.current_tenant_id()
                    AND g.status = 'active'
                    AND now() >= g.starts_at AND now() < g.expires_at)
$$;

CREATE OR REPLACE FUNCTION app.mode_in(VARIADIC p_modes text[]) RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE AS $$ SELECT app.current_access_mode() = ANY (p_modes) $$;

-- ---------------------------------------------------------------------------
-- Schema usage
-- ---------------------------------------------------------------------------
GRANT USAGE ON SCHEMA app, platform, iam, content, ingest, rag, ai, eval, audit, ops
  TO rag_app, rag_worker, rag_readonly;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app TO rag_app, rag_worker, rag_readonly;

-- =============================================================================
-- Platform-level tables (not tenant-restrictive: platform admins span tenants;
-- tenants may read only their own rows).
-- =============================================================================
-- Reference / catalogue tables readable by every service role.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['platform.tenant_plans', 'platform.platform_roles', 'platform.platform_permissions',
                           'platform.platform_role_permissions', 'platform.platform_settings',
                           'platform.ai_providers', 'platform.model_catalogue'] LOOP
    EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS ref_read ON %s', t);
    EXECUTE format('CREATE POLICY ref_read ON %s FOR SELECT USING (true)', t);
    EXECUTE format('DROP POLICY IF EXISTS ref_platform_write ON %s', t);
    EXECUTE format('CREATE POLICY ref_platform_write ON %s FOR ALL USING (app.is_platform_admin()) WITH CHECK (app.is_platform_admin())', t);
  END LOOP;
END $$;
GRANT SELECT ON platform.tenant_plans, platform.platform_roles, platform.platform_permissions,
                platform.platform_role_permissions, platform.platform_settings,
                platform.ai_providers, platform.model_catalogue TO rag_app, rag_worker, rag_readonly;
GRANT INSERT, UPDATE ON platform.tenant_plans, platform.platform_settings, platform.ai_providers,
                        platform.model_catalogue TO rag_app;

-- Tenants
ALTER TABLE platform.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.tenants FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenants_self_read ON platform.tenants;
CREATE POLICY tenants_self_read ON platform.tenants FOR SELECT USING (tenant_id = app.current_tenant_id());
DROP POLICY IF EXISTS tenants_platform_read ON platform.tenants;
CREATE POLICY tenants_platform_read ON platform.tenants FOR SELECT USING (app.is_platform_reader());
DROP POLICY IF EXISTS tenants_platform_insert ON platform.tenants;
CREATE POLICY tenants_platform_insert ON platform.tenants FOR INSERT WITH CHECK (app.is_platform_admin());
DROP POLICY IF EXISTS tenants_platform_update ON platform.tenants;
CREATE POLICY tenants_platform_update ON platform.tenants FOR UPDATE USING (app.is_platform_admin()) WITH CHECK (app.is_platform_admin());
DROP POLICY IF EXISTS tenants_activity_update ON platform.tenants;
CREATE POLICY tenants_activity_update ON platform.tenants FOR UPDATE
  USING (tenant_id = app.current_tenant_id() AND app.mode_in('user', 'tenant_admin', 'worker'))
  WITH CHECK (tenant_id = app.current_tenant_id());
-- Background schedulers enumerate tenants (id + status only are used) and then
-- process each tenant in its own validated worker context (extension 13).
DROP POLICY IF EXISTS tenants_scheduler_read ON platform.tenants;
CREATE POLICY tenants_scheduler_read ON platform.tenants FOR SELECT TO rag_worker
  USING (app.current_access_mode() = 'scheduler');
GRANT SELECT ON platform.tenants TO rag_app, rag_worker, rag_readonly;
GRANT INSERT, UPDATE ON platform.tenants TO rag_app;
GRANT UPDATE (last_activity_at) ON platform.tenants TO rag_worker;
-- No DELETE grant exists: tenants are archived, never hard-deleted by services.

-- Per-tenant platform records
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['platform.tenant_subscriptions', 'platform.tenant_quotas', 'platform.tenant_usage',
                           'platform.tenant_feature_flags', 'platform.tenant_domains', 'platform.tenant_settings'] LOOP
    EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS own_or_platform_read ON %s', t);
    EXECUTE format('CREATE POLICY own_or_platform_read ON %s FOR SELECT USING (tenant_id = app.current_tenant_id() OR app.is_platform_reader())', t);
    EXECUTE format('DROP POLICY IF EXISTS platform_write ON %s', t);
    EXECUTE format('CREATE POLICY platform_write ON %s FOR ALL USING (app.is_platform_admin()) WITH CHECK (app.is_platform_admin())', t);
  END LOOP;
END $$;
DROP POLICY IF EXISTS usage_counter_update ON platform.tenant_usage;
CREATE POLICY usage_counter_update ON platform.tenant_usage FOR UPDATE
  USING (tenant_id = app.current_tenant_id() AND app.mode_in('user', 'tenant_admin', 'worker'))
  WITH CHECK (tenant_id = app.current_tenant_id());
DROP POLICY IF EXISTS settings_tenant_admin_update ON platform.tenant_settings;
CREATE POLICY settings_tenant_admin_update ON platform.tenant_settings FOR UPDATE
  USING (tenant_id = app.current_tenant_id() AND app.mode_in('tenant_admin'))
  WITH CHECK (tenant_id = app.current_tenant_id());
GRANT SELECT ON platform.tenant_subscriptions, platform.tenant_quotas, platform.tenant_usage,
                platform.tenant_feature_flags, platform.tenant_domains, platform.tenant_settings
  TO rag_app, rag_worker, rag_readonly;
GRANT INSERT, UPDATE ON platform.tenant_subscriptions, platform.tenant_quotas, platform.tenant_usage,
                        platform.tenant_feature_flags, platform.tenant_domains, platform.tenant_settings TO rag_app;
GRANT DELETE ON platform.tenant_feature_flags, platform.tenant_domains TO rag_app;
GRANT UPDATE ON platform.tenant_usage TO rag_worker;

-- Global identity
ALTER TABLE iam.user_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE iam.user_accounts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS accounts_self ON iam.user_accounts;
CREATE POLICY accounts_self ON iam.user_accounts FOR SELECT USING (account_id = app.current_account_id());
DROP POLICY IF EXISTS accounts_self_update ON iam.user_accounts;
CREATE POLICY accounts_self_update ON iam.user_accounts FOR UPDATE
  USING (account_id = app.current_account_id()) WITH CHECK (account_id = app.current_account_id());
DROP POLICY IF EXISTS accounts_platform ON iam.user_accounts;
CREATE POLICY accounts_platform ON iam.user_accounts FOR ALL USING (app.is_platform_admin()) WITH CHECK (app.is_platform_admin());
DROP POLICY IF EXISTS accounts_platform_read ON iam.user_accounts;
CREATE POLICY accounts_platform_read ON iam.user_accounts FOR SELECT USING (app.is_platform_reader());
DROP POLICY IF EXISTS accounts_tenant_admin_read ON iam.user_accounts;
CREATE POLICY accounts_tenant_admin_read ON iam.user_accounts FOR SELECT
  USING (app.mode_in('tenant_admin', 'platform_provisioning', 'worker', 'auditor')
         AND EXISTS (SELECT 1 FROM iam.tenant_memberships m
                      WHERE m.account_id = user_accounts.account_id AND m.tenant_id = app.current_tenant_id()));
DROP POLICY IF EXISTS accounts_tenant_admin_insert ON iam.user_accounts;
CREATE POLICY accounts_tenant_admin_insert ON iam.user_accounts FOR INSERT
  WITH CHECK (app.mode_in('tenant_admin', 'platform_provisioning') AND app.current_tenant_id() IS NOT NULL);
GRANT SELECT, INSERT ON iam.user_accounts TO rag_app;
GRANT UPDATE (display_name, password_hash, mfa_enabled, mfa_secret_enc, status, failed_login_count,
              locked_until, password_changed_at) ON iam.user_accounts TO rag_app;
GRANT SELECT ON iam.user_accounts TO rag_worker, rag_readonly;

-- Platform users / roles
ALTER TABLE platform.platform_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.platform_users FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS platform_users_self ON platform.platform_users;
CREATE POLICY platform_users_self ON platform.platform_users FOR SELECT USING (account_id = app.current_account_id());
DROP POLICY IF EXISTS platform_users_read ON platform.platform_users;
CREATE POLICY platform_users_read ON platform.platform_users FOR SELECT USING (app.is_platform_reader());
DROP POLICY IF EXISTS platform_users_write ON platform.platform_users;
CREATE POLICY platform_users_write ON platform.platform_users FOR ALL USING (app.is_platform_admin()) WITH CHECK (app.is_platform_admin());
GRANT SELECT, INSERT, UPDATE ON platform.platform_users TO rag_app;

-- Platform audit: append-only.  Every service may append; only platform readers read.
ALTER TABLE platform.platform_audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.platform_audit_logs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS paudit_insert ON platform.platform_audit_logs;
CREATE POLICY paudit_insert ON platform.platform_audit_logs FOR INSERT WITH CHECK (true);
DROP POLICY IF EXISTS paudit_read ON platform.platform_audit_logs;
CREATE POLICY paudit_read ON platform.platform_audit_logs FOR SELECT USING (app.is_platform_reader());
GRANT INSERT ON platform.platform_audit_logs TO rag_app, rag_worker;
GRANT SELECT ON platform.platform_audit_logs TO rag_app, rag_readonly;

-- Break-glass grants
ALTER TABLE platform.break_glass_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.break_glass_grants FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS bg_own ON platform.break_glass_grants;
CREATE POLICY bg_own ON platform.break_glass_grants FOR SELECT USING (account_id = app.current_account_id());
DROP POLICY IF EXISTS bg_platform_read ON platform.break_glass_grants;
CREATE POLICY bg_platform_read ON platform.break_glass_grants FOR SELECT USING (app.is_platform_reader());
DROP POLICY IF EXISTS bg_platform_write ON platform.break_glass_grants;
CREATE POLICY bg_platform_write ON platform.break_glass_grants FOR ALL
  USING (app.is_platform_admin() AND account_id = app.current_account_id())
  WITH CHECK (app.is_platform_admin() AND account_id = app.current_account_id());
DROP POLICY IF EXISTS bg_record_access ON platform.break_glass_grants;
CREATE POLICY bg_record_access ON platform.break_glass_grants FOR UPDATE
  USING (app.current_access_mode() = 'break_glass' AND account_id = app.current_account_id())
  WITH CHECK (account_id = app.current_account_id());
GRANT SELECT, INSERT, UPDATE ON platform.break_glass_grants TO rag_app;
-- referenced by app.break_glass_active() inside content policies evaluated for every role
GRANT SELECT ON platform.break_glass_grants TO rag_worker, rag_readonly, rag_acl_fn;

-- Worker heartbeats
ALTER TABLE ops.worker_heartbeats ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.worker_heartbeats FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS hb_read ON ops.worker_heartbeats;
CREATE POLICY hb_read ON ops.worker_heartbeats FOR SELECT USING (app.is_platform_reader() OR app.mode_in('worker'));
DROP POLICY IF EXISTS hb_write ON ops.worker_heartbeats;
CREATE POLICY hb_write ON ops.worker_heartbeats FOR ALL TO rag_worker USING (true) WITH CHECK (true);
GRANT SELECT ON ops.worker_heartbeats TO rag_app, rag_readonly;
GRANT SELECT, INSERT, UPDATE ON ops.worker_heartbeats TO rag_worker;

-- Global permission catalogue: no tenant data, read-only reference => no RLS.
GRANT SELECT ON iam.permissions TO rag_app, rag_worker, rag_readonly;

-- =============================================================================
-- Tenant-owned tables: RESTRICTIVE tenant isolation everywhere
-- =============================================================================
SELECT app_admin.apply_tenant_rls(t::regclass) FROM unnest(ARRAY[
  'iam.departments', 'iam.users', 'iam.tenant_memberships', 'iam.teams', 'iam.team_members',
  'iam.user_groups', 'iam.user_group_members', 'iam.roles', 'iam.role_permissions', 'iam.user_roles',
  'iam.user_attributes',
  'content.collections', 'content.collection_access', 'content.documents', 'content.document_versions',
  'content.document_metadata', 'content.document_access', 'content.document_pages',
  'content.document_chunks', 'content.chunk_embeddings',
  'ingest.ingestion_jobs', 'ingest.ingestion_job_logs']) AS t;

-- ---------------------------------------------------------------------------
-- iam: directory data.  Users see their own profile, memberships, groups and
-- roles (needed for principal resolution); administrators see the tenant
-- directory; writes only by tenant administration / provisioning.
-- ---------------------------------------------------------------------------
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['iam.departments', 'iam.users', 'iam.tenant_memberships', 'iam.teams', 'iam.team_members',
                           'iam.user_groups', 'iam.user_group_members', 'iam.roles', 'iam.role_permissions',
                           'iam.user_roles', 'iam.user_attributes'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS admin_read ON %s', t);
    EXECUTE format($f$CREATE POLICY admin_read ON %s FOR SELECT
                      USING (app.mode_in('tenant_admin', 'auditor', 'worker', 'platform_provisioning'))$f$, t);
    EXECUTE format('DROP POLICY IF EXISTS admin_write ON %s', t);
    EXECUTE format($f$CREATE POLICY admin_write ON %s FOR ALL
                      USING (app.mode_in('tenant_admin', 'platform_provisioning'))
                      WITH CHECK (app.mode_in('tenant_admin', 'platform_provisioning'))$f$, t);
  END LOOP;
END $$;
DROP POLICY IF EXISTS self_read ON iam.users;
CREATE POLICY self_read ON iam.users FOR SELECT USING (app.mode_in('user', 'break_glass') AND user_id = app.current_user_id());
DROP POLICY IF EXISTS self_activity ON iam.users;
CREATE POLICY self_activity ON iam.users FOR UPDATE USING (app.mode_in('user') AND user_id = app.current_user_id())
  WITH CHECK (user_id = app.current_user_id());
DROP POLICY IF EXISTS self_read ON iam.tenant_memberships;
CREATE POLICY self_read ON iam.tenant_memberships FOR SELECT USING (account_id = app.current_account_id());
DROP POLICY IF EXISTS directory_read ON iam.departments;
CREATE POLICY directory_read ON iam.departments FOR SELECT USING (app.mode_in('user'));
DROP POLICY IF EXISTS directory_read ON iam.teams;
CREATE POLICY directory_read ON iam.teams FOR SELECT USING (app.mode_in('user'));
DROP POLICY IF EXISTS self_read ON iam.team_members;
CREATE POLICY self_read ON iam.team_members FOR SELECT USING (app.mode_in('user') AND user_id = app.current_user_id());
DROP POLICY IF EXISTS self_read ON iam.user_group_members;
CREATE POLICY self_read ON iam.user_group_members FOR SELECT USING (app.mode_in('user') AND user_id = app.current_user_id());
DROP POLICY IF EXISTS member_read ON iam.user_groups;
CREATE POLICY member_read ON iam.user_groups FOR SELECT USING (app.mode_in('user') AND EXISTS (
  SELECT 1 FROM iam.user_group_members g WHERE g.group_id = user_groups.group_id AND g.user_id = app.current_user_id()));
DROP POLICY IF EXISTS self_read ON iam.user_roles;
CREATE POLICY self_read ON iam.user_roles FOR SELECT USING (app.mode_in('user') AND user_id = app.current_user_id());
DROP POLICY IF EXISTS holder_read ON iam.roles;
CREATE POLICY holder_read ON iam.roles FOR SELECT USING (app.mode_in('user') AND EXISTS (
  SELECT 1 FROM iam.user_roles r WHERE r.role_id = roles.role_id AND r.user_id = app.current_user_id()));
DROP POLICY IF EXISTS holder_read ON iam.role_permissions;
CREATE POLICY holder_read ON iam.role_permissions FOR SELECT USING (app.mode_in('user') AND EXISTS (
  SELECT 1 FROM iam.user_roles r WHERE r.role_id = role_permissions.role_id AND r.user_id = app.current_user_id()));
DROP POLICY IF EXISTS self_read ON iam.user_attributes;
CREATE POLICY self_read ON iam.user_attributes FOR SELECT USING (app.mode_in('user') AND user_id = app.current_user_id());

GRANT SELECT, INSERT, UPDATE ON iam.departments, iam.users, iam.tenant_memberships, iam.teams, iam.team_members,
                                iam.user_groups, iam.user_group_members, iam.roles, iam.role_permissions,
                                iam.user_roles, iam.user_attributes TO rag_app;
GRANT DELETE ON iam.team_members, iam.user_group_members, iam.role_permissions, iam.user_roles,
                iam.user_attributes, iam.teams, iam.user_groups, iam.roles TO rag_app;
GRANT SELECT ON iam.departments, iam.users, iam.tenant_memberships, iam.teams, iam.team_members, iam.user_groups,
                iam.user_group_members, iam.roles, iam.role_permissions, iam.user_roles, iam.user_attributes
  TO rag_worker, rag_readonly;

-- Sessions and login history (account scoped, tenant administrators can see /
-- revoke their tenant's sessions).  Creation happens through SECURITY DEFINER
-- auth functions (functions.sql).
ALTER TABLE iam.sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE iam.sessions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sessions_own ON iam.sessions;
CREATE POLICY sessions_own ON iam.sessions FOR SELECT USING (account_id = app.current_account_id());
DROP POLICY IF EXISTS sessions_own_revoke ON iam.sessions;
CREATE POLICY sessions_own_revoke ON iam.sessions FOR UPDATE USING (account_id = app.current_account_id())
  WITH CHECK (account_id = app.current_account_id());
DROP POLICY IF EXISTS sessions_tenant_admin ON iam.sessions;
CREATE POLICY sessions_tenant_admin ON iam.sessions FOR ALL
  USING (tenant_id = app.current_tenant_id() AND app.mode_in('tenant_admin'))
  WITH CHECK (tenant_id = app.current_tenant_id() AND app.mode_in('tenant_admin'));
DROP POLICY IF EXISTS sessions_platform ON iam.sessions;
CREATE POLICY sessions_platform ON iam.sessions FOR SELECT USING (app.is_platform_reader());
DROP POLICY IF EXISTS sessions_platform_revoke ON iam.sessions;
CREATE POLICY sessions_platform_revoke ON iam.sessions FOR UPDATE USING (app.is_platform_admin()) WITH CHECK (app.is_platform_admin());
GRANT SELECT ON iam.sessions TO rag_app;
GRANT UPDATE (revoked_at, revoked_reason, last_seen_at) ON iam.sessions TO rag_app;

ALTER TABLE iam.refresh_tokens ENABLE ROW LEVEL SECURITY;          -- no service policy: definer functions only
ALTER TABLE iam.refresh_tokens FORCE ROW LEVEL SECURITY;
ALTER TABLE iam.password_reset_tokens ENABLE ROW LEVEL SECURITY;   -- definer functions only
ALTER TABLE iam.password_reset_tokens FORCE ROW LEVEL SECURITY;

ALTER TABLE iam.login_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE iam.login_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS login_own ON iam.login_events;
CREATE POLICY login_own ON iam.login_events FOR SELECT USING (account_id = app.current_account_id());
DROP POLICY IF EXISTS login_tenant_admin ON iam.login_events;
CREATE POLICY login_tenant_admin ON iam.login_events FOR SELECT
  USING (app.mode_in('tenant_admin', 'auditor') AND (tenant_id = app.current_tenant_id() OR EXISTS (
         SELECT 1 FROM iam.tenant_memberships m WHERE m.account_id = login_events.account_id
                                                AND m.tenant_id = app.current_tenant_id())));
DROP POLICY IF EXISTS login_platform ON iam.login_events;
CREATE POLICY login_platform ON iam.login_events FOR SELECT USING (app.is_platform_reader());
GRANT SELECT ON iam.login_events TO rag_app, rag_readonly;

-- ---------------------------------------------------------------------------
-- content
-- ---------------------------------------------------------------------------
-- Collections: admins/workers see all; users see collections granted to them.
DROP POLICY IF EXISTS admin_all ON content.collections;
CREATE POLICY admin_all ON content.collections FOR ALL
  USING (app.mode_in('tenant_admin', 'worker')) WITH CHECK (app.mode_in('tenant_admin', 'worker'));
DROP POLICY IF EXISTS reader_read ON content.collections;
CREATE POLICY reader_read ON content.collections FOR SELECT USING (app.mode_in('auditor', 'break_glass'));
DROP POLICY IF EXISTS member_read ON content.collections;
CREATE POLICY member_read ON content.collections FOR SELECT USING (app.mode_in('user') AND EXISTS (
  SELECT 1 FROM content.collection_access a
   WHERE a.collection_id = collections.collection_id AND a.effect = 'allow'
     AND COALESCE(a.principal_id, collections.tenant_id) = ANY (app.current_principals())));

DROP POLICY IF EXISTS admin_all ON content.collection_access;
CREATE POLICY admin_all ON content.collection_access FOR ALL
  USING (app.mode_in('tenant_admin', 'worker')) WITH CHECK (app.mode_in('tenant_admin'));
DROP POLICY IF EXISTS member_read ON content.collection_access;
CREATE POLICY member_read ON content.collection_access FOR SELECT
  USING (app.mode_in('user', 'auditor') AND COALESCE(principal_id, tenant_id) = ANY (app.current_principals()));

-- Documents: metadata.  Users: ACL predicate, or their own uploads while they
-- are being processed.  Tenant admins see the inventory metadata only.
DROP POLICY IF EXISTS user_read ON content.documents;
CREATE POLICY user_read ON content.documents FOR SELECT USING (
  app.mode_in('user') AND (
    app.acl_visible(classification_rank, insurance_line, jurisdictions, lifecycle_state, allow_principals, deny_principals)
    OR created_by = app.current_user_id()));
DROP POLICY IF EXISTS user_insert ON content.documents;
CREATE POLICY user_insert ON content.documents FOR INSERT
  WITH CHECK (app.mode_in('user') AND created_by = app.current_user_id());
DROP POLICY IF EXISTS owner_update ON content.documents;
CREATE POLICY owner_update ON content.documents FOR UPDATE
  USING (app.mode_in('user') AND (owner_user_id = app.current_user_id() OR created_by = app.current_user_id()))
  WITH CHECK (app.mode_in('user') AND (owner_user_id = app.current_user_id() OR created_by = app.current_user_id()));
DROP POLICY IF EXISTS admin_all ON content.documents;
CREATE POLICY admin_all ON content.documents FOR ALL
  USING (app.mode_in('tenant_admin', 'worker')) WITH CHECK (app.mode_in('tenant_admin', 'worker'));
DROP POLICY IF EXISTS reader_read ON content.documents;
CREATE POLICY reader_read ON content.documents FOR SELECT USING (app.mode_in('auditor') OR app.break_glass_active());

-- Versions and metadata follow the parent document's visibility.
DROP POLICY IF EXISTS via_document ON content.document_versions;
CREATE POLICY via_document ON content.document_versions FOR SELECT USING (
  app.mode_in('user', 'auditor', 'break_glass') AND EXISTS (SELECT 1 FROM content.documents d WHERE d.document_id = document_versions.document_id));
DROP POLICY IF EXISTS uploader_insert ON content.document_versions;
CREATE POLICY uploader_insert ON content.document_versions FOR INSERT WITH CHECK (
  app.mode_in('user') AND created_by = app.current_user_id()
  AND EXISTS (SELECT 1 FROM content.documents d WHERE d.document_id = document_versions.document_id));
DROP POLICY IF EXISTS admin_all ON content.document_versions;
CREATE POLICY admin_all ON content.document_versions FOR ALL
  USING (app.mode_in('tenant_admin', 'worker')) WITH CHECK (app.mode_in('tenant_admin', 'worker'));

DROP POLICY IF EXISTS via_version ON content.document_metadata;
CREATE POLICY via_version ON content.document_metadata FOR SELECT USING (
  app.mode_in('user', 'auditor', 'break_glass') AND EXISTS (SELECT 1 FROM content.document_versions v WHERE v.version_id = document_metadata.version_id));
DROP POLICY IF EXISTS uploader_insert ON content.document_metadata;
CREATE POLICY uploader_insert ON content.document_metadata FOR INSERT WITH CHECK (
  app.mode_in('user') AND EXISTS (SELECT 1 FROM content.document_versions v WHERE v.version_id = document_metadata.version_id
                                                                         AND v.created_by = app.current_user_id()));
DROP POLICY IF EXISTS admin_all ON content.document_metadata;
CREATE POLICY admin_all ON content.document_metadata FOR ALL
  USING (app.mode_in('tenant_admin', 'worker')) WITH CHECK (app.mode_in('tenant_admin', 'worker'));

DROP POLICY IF EXISTS admin_all ON content.document_access;
CREATE POLICY admin_all ON content.document_access FOR ALL
  USING (app.mode_in('tenant_admin', 'worker')) WITH CHECK (app.mode_in('tenant_admin', 'worker'));
DROP POLICY IF EXISTS auditor_read ON content.document_access;
CREATE POLICY auditor_read ON content.document_access FOR SELECT USING (app.mode_in('auditor'));

-- Pages and chunks are CONTENT: never visible to tenant_admin (SP-08).
DROP POLICY IF EXISTS via_document ON content.document_pages;
CREATE POLICY via_document ON content.document_pages FOR SELECT USING (
  (app.mode_in('user') OR app.break_glass_active())
  AND EXISTS (SELECT 1 FROM content.documents d WHERE d.document_id = document_pages.document_id
                AND app.acl_visible(d.classification_rank, d.insurance_line, d.jurisdictions, d.lifecycle_state,
                                    d.allow_principals, d.deny_principals) OR app.break_glass_active()));
DROP POLICY IF EXISTS worker_all ON content.document_pages;
CREATE POLICY worker_all ON content.document_pages FOR ALL USING (app.mode_in('worker')) WITH CHECK (app.mode_in('worker'));

DROP POLICY IF EXISTS acl_read ON content.document_chunks;
CREATE POLICY acl_read ON content.document_chunks FOR SELECT USING (
  (app.mode_in('user')
   AND app.acl_visible(classification_rank, line_of_business, jurisdictions, lifecycle_state, allow_principals, deny_principals))
  OR app.break_glass_active());
DROP POLICY IF EXISTS worker_all ON content.document_chunks;
CREATE POLICY worker_all ON content.document_chunks FOR ALL USING (app.mode_in('worker')) WITH CHECK (app.mode_in('worker'));
DROP POLICY IF EXISTS acl_read ON content.chunk_embeddings;
CREATE POLICY acl_read ON content.chunk_embeddings FOR SELECT USING (
  (app.mode_in('user')
   AND app.acl_visible(classification_rank, line_of_business, jurisdictions, lifecycle_state, allow_principals, deny_principals))
  OR app.break_glass_active());
DROP POLICY IF EXISTS worker_all ON content.chunk_embeddings;
CREATE POLICY worker_all ON content.chunk_embeddings FOR ALL USING (app.mode_in('worker')) WITH CHECK (app.mode_in('worker'));
-- ACL propagation to chunks / embeddings runs inside app.refresh_document_acl(),
-- a SECURITY DEFINER function owned by rag_acl_fn (see functions section of
-- 06_chunks_embeddings.sql).  Tenant administrators therefore never need -
-- and never get - read access to chunk content.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['content.documents', 'content.document_chunks', 'content.chunk_embeddings',
                           'content.document_access', 'content.collection_access', 'content.document_versions',
                           'platform.tenant_usage'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS acl_fn_all ON %s', t);
    EXECUTE format('CREATE POLICY acl_fn_all ON %s FOR ALL TO rag_acl_fn USING (tenant_id = app.current_tenant_id()) WITH CHECK (tenant_id = app.current_tenant_id())', t);
  END LOOP;
END $$;
GRANT USAGE ON SCHEMA app, content, platform TO rag_acl_fn;
GRANT SELECT ON platform.tenants TO rag_acl_fn;
GRANT SELECT, UPDATE ON content.documents, content.document_chunks, content.chunk_embeddings, platform.tenant_usage TO rag_acl_fn;
GRANT SELECT ON content.document_access, content.collection_access, content.document_versions TO rag_acl_fn;
GRANT CREATE ON SCHEMA app TO rag_acl_fn;   -- required transiently to transfer ownership
ALTER FUNCTION app.refresh_document_acl(uuid) OWNER TO rag_acl_fn;
REVOKE CREATE ON SCHEMA app FROM rag_acl_fn;
REVOKE ALL ON FUNCTION app.refresh_document_acl(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.refresh_document_acl(uuid) TO rag_app, rag_worker;

GRANT SELECT ON content.collections, content.collection_access, content.documents, content.document_versions,
                content.document_metadata, content.document_access, content.document_pages,
                content.document_chunks, content.chunk_embeddings TO rag_app, rag_readonly;
GRANT INSERT, UPDATE ON content.collections, content.collection_access, content.documents,
                        content.document_versions, content.document_metadata, content.document_access TO rag_app;
GRANT DELETE ON content.collection_access, content.document_access, content.document_metadata, content.collections TO rag_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON content.collections, content.collection_access, content.documents,
      content.document_versions, content.document_metadata, content.document_access, content.document_pages,
      content.document_chunks, content.chunk_embeddings TO rag_worker;

-- ---------------------------------------------------------------------------
-- ingest
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS admin_all ON ingest.ingestion_jobs;
CREATE POLICY admin_all ON ingest.ingestion_jobs FOR ALL
  USING (app.mode_in('tenant_admin', 'worker')) WITH CHECK (app.mode_in('tenant_admin', 'worker'));
DROP POLICY IF EXISTS initiator_read ON ingest.ingestion_jobs;
CREATE POLICY initiator_read ON ingest.ingestion_jobs FOR SELECT
  USING (app.mode_in('user') AND initiated_by = app.current_user_id());
DROP POLICY IF EXISTS initiator_insert ON ingest.ingestion_jobs;
CREATE POLICY initiator_insert ON ingest.ingestion_jobs FOR INSERT
  WITH CHECK (app.mode_in('user') AND initiated_by = app.current_user_id());
DROP POLICY IF EXISTS auditor_read ON ingest.ingestion_jobs;
CREATE POLICY auditor_read ON ingest.ingestion_jobs FOR SELECT USING (app.mode_in('auditor'));

DROP POLICY IF EXISTS admin_all ON ingest.ingestion_job_logs;
CREATE POLICY admin_all ON ingest.ingestion_job_logs FOR ALL
  USING (app.mode_in('tenant_admin', 'worker', 'auditor')) WITH CHECK (app.mode_in('worker', 'tenant_admin'));
DROP POLICY IF EXISTS initiator_read ON ingest.ingestion_job_logs;
CREATE POLICY initiator_read ON ingest.ingestion_job_logs FOR SELECT USING (app.mode_in('user') AND EXISTS (
  SELECT 1 FROM ingest.ingestion_jobs j WHERE j.job_id = ingestion_job_logs.job_id));

GRANT SELECT, INSERT, UPDATE ON ingest.ingestion_jobs, ingest.ingestion_job_logs TO rag_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ingest.ingestion_jobs, ingest.ingestion_job_logs TO rag_worker;
GRANT SELECT ON ingest.ingestion_jobs, ingest.ingestion_job_logs TO rag_readonly;
