"""Portable export-folder aliases and lossless consolidation of old exports."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src.runtime_paths import export_directory, normalize_export_folder, consolidate_export_folders


class TestExportPaths(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_legacy_default_and_subfolders_resolve_to_one_root(self):
        for value in ('', 'export', 'exports', './exports', str(self.root / 'exports')):
            self.assertEqual(normalize_export_folder(value, self.root), str(self.root / 'export'))
        self.assertEqual(normalize_export_folder('exports/reports', self.root), str(self.root / 'export/reports'))

    def test_external_and_dotted_custom_folders_are_preserved(self):
        external = self.root.parent / 'custom' / 'exports'
        self.assertEqual(normalize_export_folder(str(external), self.root), str(external))
        self.assertEqual(normalize_export_folder('exports.v17', self.root), str(self.root / 'exports.v17'))

    def test_old_file_path_normalizes_to_new_folder(self):
        self.assertEqual(normalize_export_folder('exports/old.properties', self.root), str(self.root / 'export'))

    def test_existing_directory_with_file_like_suffix_is_preserved(self):
        directory = self.root / 'reports.ini'
        directory.mkdir()
        self.assertEqual(normalize_export_folder(str(directory), self.root), str(directory))

    def test_only_old_root_is_renamed_with_all_content(self):
        old = self.root / 'exports'
        (old / 'reports').mkdir(parents=True)
        (old / 'reports/data.csv').write_bytes(b'old data')
        self.assertIsNone(consolidate_export_folders(self.root))
        self.assertFalse(old.exists())
        self.assertEqual((self.root / 'export/reports/data.csv').read_bytes(), b'old data')

    def test_two_roots_preserve_both_versions_without_overwrite(self):
        old, new = self.root / 'exports', self.root / 'export'
        old.mkdir(); new.mkdir()
        (old / 'same.csv').write_bytes(b'previous export')
        (new / 'same.csv').write_bytes(b'new export')
        (new / 'incident').mkdir()
        self.assertIsNone(consolidate_export_folders(self.root))
        self.assertFalse(old.exists())
        archives = list(new.glob('legacy_exports_*'))
        self.assertEqual(len(archives), 1)
        self.assertEqual((archives[0] / 'same.csv').read_bytes(), b'previous export')
        self.assertEqual((new / 'same.csv').read_bytes(), b'new export')
        self.assertTrue((new / 'incident').is_dir())
        self.assertIsNone(consolidate_export_folders(self.root))
        self.assertEqual(list(new.glob('legacy_exports_*')), archives)

    def test_locked_legacy_folder_is_retained_for_retry(self):
        old = self.root / 'exports'
        old.mkdir()
        (old / 'data.txt').write_bytes(b'keep')
        with patch.object(Path, 'rename', side_effect=PermissionError('in use')):
            warning = consolidate_export_folders(self.root)
        self.assertIn('original files retained', warning)
        self.assertEqual((old / 'data.txt').read_bytes(), b'keep')
        self.assertIsNone(consolidate_export_folders(self.root))
        self.assertEqual((self.root / 'export/data.txt').read_bytes(), b'keep')

    def test_resolving_folder_does_not_create_it(self):
        self.assertEqual(export_directory(self.root), str(self.root / 'export'))
        self.assertFalse((self.root / 'export').exists())
