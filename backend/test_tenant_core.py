import unittest

from tenant_core import effective_modules, tenant_access_allowed, tenant_feature_enabled


class TenantCoreTests(unittest.TestCase):
    def test_feature_flag_is_off_unless_explicitly_enabled(self):
        self.assertFalse(tenant_feature_enabled(None))
        self.assertFalse(tenant_feature_enabled("false"))
        self.assertTrue(tenant_feature_enabled("true"))
        self.assertTrue(tenant_feature_enabled("1"))

    def test_disabled_policy_preserves_legacy_access_and_permissions(self):
        self.assertTrue(tenant_access_allowed(
            feature_enabled=False,
            actor_role="operator",
            actor_tenant_id=None,
            resource_tenant_id=42,
        ))
        self.assertEqual(
            effective_modules(
                feature_enabled=False,
                actor_role="operator",
                user_modules={"Atendimento"},
                plan_modules=set(),
            ),
            frozenset({"Atendimento"}),
        )

    def test_tenant_user_can_access_only_its_company_records(self):
        self.assertTrue(tenant_access_allowed(
            feature_enabled=True,
            actor_role="tenant_admin",
            actor_tenant_id=10,
            resource_tenant_id=10,
        ))
        self.assertFalse(tenant_access_allowed(
            feature_enabled=True,
            actor_role="tenant_admin",
            actor_tenant_id=10,
            resource_tenant_id=11,
        ))
        self.assertFalse(tenant_access_allowed(
            feature_enabled=True,
            actor_role="tenant_admin",
            actor_tenant_id=10,
            resource_tenant_id=None,
        ))

    def test_platform_admin_can_access_legacy_and_tenant_records(self):
        for resource_tenant_id in (None, 10, 11):
            self.assertTrue(tenant_access_allowed(
                feature_enabled=True,
                actor_role="admin",
                actor_tenant_id=None,
                resource_tenant_id=resource_tenant_id,
            ))

    def test_tenant_modules_are_capped_by_plan(self):
        self.assertEqual(
            effective_modules(
                feature_enabled=True,
                actor_role="tenant_admin",
                user_modules={"Atendimento", "Suporte"},
                plan_modules={"Atendimento"},
            ),
            frozenset({"Atendimento"}),
        )

    def test_platform_admin_is_not_capped_by_a_tenant_plan(self):
        self.assertIsNone(effective_modules(
            feature_enabled=True,
            actor_role="admin",
            user_modules={"Atendimento"},
            plan_modules=set(),
        ))


if __name__ == "__main__":
    unittest.main()
