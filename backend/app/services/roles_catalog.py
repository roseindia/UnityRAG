"""System role templates copied into every tenant at provisioning.

System roles are flagged is_system and protected from modification by tenant
administrators (extension 7.3).  `conflicts_with` implements segregation of
duties (FR-165): an auditor may not simultaneously administer the tenant.
"""
from __future__ import annotations

USER_PERMISSIONS = ["documents.read", "collections.read", "search.use", "chat.use", "feedback.submit"]

SYSTEM_ROLES: list[dict] = [
    {"code": "tenant_admin", "name": "Tenant Administrator", "is_admin": True, "conflicts_with": ["auditor"],
     "permissions": USER_PERMISSIONS + [
         "documents.upload", "documents.download", "documents.manage", "documents.delete", "feedback.review",
         "admin.dashboard.view", "admin.users.manage", "admin.roles.manage", "admin.departments.manage",
         "admin.groups.manage", "admin.documents.manage", "admin.collections.manage", "admin.ingestion.manage",
         "admin.ai_config.manage", "admin.rag_config.manage", "admin.analytics.view", "admin.usage.view",
         "admin.audit.view", "admin.settings.manage", "admin.reports.export", "evaluation.manage", "evaluation.run"]},
    {"code": "knowledge_manager", "name": "Knowledge Manager", "is_admin": True, "conflicts_with": [],
     "permissions": USER_PERMISSIONS + [
         "documents.upload", "documents.download", "documents.manage", "documents.delete", "feedback.review",
         "admin.dashboard.view", "admin.documents.manage", "admin.collections.manage", "admin.ingestion.manage",
         "evaluation.manage", "evaluation.run"]},
    {"code": "department_admin", "name": "Department Administrator", "is_admin": True, "conflicts_with": [],
     "permissions": USER_PERMISSIONS + ["department.analytics.view", "documents.upload"]},
    {"code": "auditor", "name": "Auditor", "is_admin": True, "conflicts_with": ["tenant_admin"],
     "permissions": ["admin.audit.view", "admin.analytics.view", "admin.usage.view", "admin.reports.export"]},
    {"code": "document_contributor", "name": "Document Contributor", "is_admin": False, "conflicts_with": [],
     "permissions": USER_PERMISSIONS + ["documents.upload", "documents.manage", "documents.download"]},
    {"code": "member", "name": "Member", "is_admin": False, "conflicts_with": [],
     "permissions": USER_PERMISSIONS + ["documents.download"]},
    {"code": "external_partner", "name": "Broker / Agent", "is_admin": False, "conflicts_with": [],
     "permissions": ["documents.read", "collections.read", "search.use", "chat.use", "feedback.submit"]},
]
SYSTEM_ROLE_CODES = {r["code"] for r in SYSTEM_ROLES}
