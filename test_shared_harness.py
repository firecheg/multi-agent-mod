import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('shared_harness', Path(__file__).parent / 'execution/shared_harness.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / 'home'
        self.shared = self.home / '.agent-harness'
        self.mam = Path(self.tmp.name) / 'mam'
        self.mam.mkdir()
        for host in ('.claude', '.codex'):
            skill = self.home / host / 'skills' / 'demo'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text(host, encoding='utf-8')
        (self.home / '.codex/skills/demo/extra.txt').write_text('preserve', encoding='utf-8')
        (self.home / '.codex/AGENTS.md').write_text('original codex', encoding='utf-8')
        (self.home / '.claude/CLAUDE.md').write_text('original claude', encoding='utf-8')

    def tearDown(self):
        # Перед очисткой фикстуры убираем junction, не затрагивая его цель.
        for host in ('.claude', '.codex'):
            p = self.home / host / 'skills/demo'
            if p.is_junction():
                os.rmdir(p)
        self.tmp.cleanup()

    def test_plan_is_read_only_and_reports_conflict(self):
        plan = module.plan(self.home, self.shared, self.mam)
        self.assertFalse(self.shared.exists())
        self.assertEqual(plan['skills']['demo']['source'], str(self.home / '.claude/skills/demo'))
        self.assertTrue(plan['conflicts'])

    def test_apply_idempotent_common_identity_and_rollback(self):
        result = module.apply(self.home, self.shared, self.mam, 'common rules')
        a = self.home / '.claude/skills/demo/SKILL.md'
        b = self.home / '.codex/skills/demo/SKILL.md'
        self.assertTrue(os.path.samefile(a, b))
        self.assertEqual(a.read_text(encoding='utf-8'), '.claude')
        self.assertEqual((b.parent / 'extra.txt').read_text(), 'preserve')
        self.assertTrue(os.path.samefile(self.home / '.codex/AGENTS.md', self.shared / 'rules/AGENTS.md'))
        again = module.apply(self.home, self.shared, self.mam, 'common rules')
        self.assertEqual(result['transaction'], again['transaction'])
        module.rollback(self.home, self.shared)
        self.assertEqual(a.read_text(encoding='utf-8'), '.claude')
        self.assertEqual(b.read_text(encoding='utf-8'), '.codex')
        self.assertEqual((self.home / '.codex/AGENTS.md').read_text(), 'original codex')
        self.assertEqual((self.home / '.claude/CLAUDE.md').read_text(), 'original claude')

    def test_rollback_refuses_to_overwrite_changed_configuration(self):
        module.apply(self.home, self.shared, self.mam, 'common rules')
        p = self.home / '.claude/CLAUDE.md'
        p.write_text('user edited', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed'):
            module.rollback(self.home, self.shared)
        self.assertEqual(p.read_text(), 'user edited')
        self.assertTrue((self.home / '.codex/skills/demo').is_junction())

    def test_outside_home_refused(self):
        with self.assertRaises(ValueError):
            module.apply(self.home, Path(self.tmp.name) / 'outside', self.mam, 'rules')

    def test_register_is_idempotent_and_rollback_preserves_source(self):
        module.apply(self.home, self.shared, self.mam, 'common rules')
        source = self.shared / 'skills' / 'new-skill'
        source.mkdir()
        (source / 'SKILL.md').write_text('new skill', encoding='utf-8')
        module.register(self.home, self.shared, self.mam, source)
        module.register(self.home, self.shared, self.mam, source)
        for host in ('.claude', '.codex'):
            self.assertTrue(os.path.samefile(self.home / host / 'skills/new-skill', source))
        module.rollback(self.home, self.shared)
        self.assertEqual((source / 'SKILL.md').read_text(), 'new skill')
        for host in ('.claude', '.codex'):
            self.assertFalse((self.home / host / 'skills/new-skill').exists())

    def test_unregistered_external_skill_link_refused(self):
        outside=Path(self.tmp.name)/'external';outside.mkdir()
        (outside/'SKILL.md').write_text('external',encoding='utf-8')
        link=self.home/'.claude/skills/external'
        module.junction(link,outside)
        try:
            with self.assertRaisesRegex(ValueError,'external skill link'):
                module.plan(self.home,self.shared,self.mam)
        finally:
            os.rmdir(link) if os.name=='nt' else link.unlink()


if __name__ == '__main__':
    unittest.main()
