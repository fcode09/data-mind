import sys, pathlib, unittest
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
import prepare_container_models as m
class Tests(unittest.TestCase):
    def test_llm_is_exactly_pinned(self):
        self.assertEqual(len(m.LLM['sha256']), 64)
        self.assertIn('23749fefcc72300e3a2ad315e1317431b06b590a',m.LLM['url'])
        self.assertEqual(m.LLM['size'],639446688)
    def test_llm_preparation(self):
        with patch.object(m,'acquire') as a:
            m.prepare('llm',pathlib.Path('/models'),pathlib.Path('/browser'))
            a.assert_called_once_with(m.LLM,pathlib.Path('/models/llama'))
    def test_voice_destinations(self):
        with patch.object(m,'acquire',return_value=pathlib.Path('/downloaded')) as a, patch.object(m,'browser_archive') as b:
            m.prepare('voice',pathlib.Path('/models'),pathlib.Path('/browser'))
            self.assertGreater(a.call_count,len(m.EMBEDDING_FILES))
            b.assert_called_once_with(pathlib.Path('/downloaded'),pathlib.Path('/browser/vosk-model-small-es-0.42.tar.gz'))
            self.assertTrue(any(call.args[1] == pathlib.Path('/models/multilingual-e5-small') for call in a.call_args_list))
if __name__=='__main__': unittest.main()
