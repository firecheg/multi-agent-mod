import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('client_adapters',Path(__file__).parent/'execution/client_adapters.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class AdapterTests(unittest.TestCase):
    def test_managed_settings_idempotent_rollback_preserves_other_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);shared=home/'.agent-harness';mam=home/'mam'
            (home/'.codex').mkdir()
            (home/'.codex/config.toml').write_text('model = "original"\n')
            m.write(home/'.claude/settings.json',{'theme':'dark'})
            m.configure(home,shared,mam,'python.exe')
            m.configure(home,shared,mam,'python.exe')
            data=m.load(home/'.claude.json');data['other']='new';m.write(home/'.claude.json',data)
            self.assertEqual(m.issues(shared),[])
            m.rollback(shared)
            self.assertEqual(m.load(home/'.claude.json')['other'],'new')
            self.assertIsNone(m.get(m.load(home/'.claude.json'),['mcpServers','agent_harness']))
            self.assertEqual((home/'.codex/config.toml').read_text(),'model = "original"\n')

    def test_preexisting_server_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);(home/'.codex').mkdir()
            (home/'.codex/config.toml').write_text('[mcp_servers.agent_harness]\ncommand="custom"\n')
            with self.assertRaises(ValueError):m.configure(home,home/'.agent-harness',home/'mam','python')
            self.assertIn('custom',(home/'.codex/config.toml').read_text())

    def test_interrupted_configuration_can_be_rolled_back_and_retried(self):
        for resume in (False, True):
            with self.subTest(resume=resume), tempfile.TemporaryDirectory() as tmp:
                home=Path(tmp);shared=home/'.agent-harness';mam=home/'mam'
                (home/'.codex').mkdir()
                (home/'.codex/config.toml').write_text('model = "original"\n')
                original_write=m.write
                def interrupt_after_first_setting(path, value):
                    original_write(path,value)
                    if path==home/'.claude.json':
                        raise KeyboardInterrupt('simulated process interruption')
                with patch.object(m,'write',side_effect=interrupt_after_first_setting):
                    with self.assertRaises(KeyboardInterrupt):
                        m.configure(home,shared,mam,'python')
                self.assertEqual(m.load(shared/'adapters.json')['status'],'applying')
                if resume:
                    m.configure(home,shared,mam,'python')
                    self.assertEqual(m.issues(shared),[])
                m.rollback(shared)
                self.assertIsNone(m.get(m.load(home/'.claude.json'),['mcpServers','agent_harness']))
                self.assertEqual((home/'.codex/config.toml').read_text(),'model = "original"\n')

    def test_partial_recovery_refuses_changed_managed_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);shared=home/'.agent-harness'
            (home/'.codex').mkdir()
            m.configure(home,shared,home/'mam','python')
            state=m.load(shared/'adapters.json');state['status']='applying'
            m.write(shared/'adapters.json',state)
            settings=home/'.claude/settings.json'
            data=m.load(settings);data['hooks']['PreToolUse']=[{'user':'changed'}]
            m.write(settings,data)
            original=(home/'.claude.json').read_bytes()
            with self.assertRaisesRegex(ValueError,'changed managed setting'):
                m.rollback(shared)
            self.assertEqual((home/'.claude.json').read_bytes(),original)
            self.assertEqual(m.load(settings),data)


if __name__=='__main__':unittest.main()
