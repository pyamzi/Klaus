from __future__ import annotations

import contextlib
import hashlib
import gzip
import importlib
import io
import json
import os
import sys
import tarfile
import tempfile
import threading
import unittest
import zipfile
from unittest.mock import Mock, patch

sys.path.insert(0, '.claude/skills/klaus-test/scripts')
from anki_stubs import install
install()
runtime = importlib.import_module('klaus_note.ollama_runtime')


class Response(io.BytesIO):
    headers = {}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(runtime, '_USER_FILES', self.tmp.name))
        self.manager = runtime.ServerManager()
        self.stack.enter_context(patch.object(runtime, 'server_manager', self.manager))
        self.probe = self.stack.enter_context(patch.object(runtime, 'ollama_reachable', return_value=False))
        self.system = self.stack.enter_context(patch.object(runtime, 'find_system_ollama', return_value=None))
        self.popen = self.stack.enter_context(patch.object(runtime.subprocess, 'Popen', side_effect=AssertionError('real process forbidden')))
        self.network = self.stack.enter_context(patch.object(runtime.urllib.request, 'urlopen', side_effect=AssertionError('real download forbidden')))
        self.stack.enter_context(patch.object(runtime.subprocess, 'run', side_effect=AssertionError('system command forbidden')))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.cfg = {'endpoint': 'http://127.0.0.1:11434'}

    def test_missing_runtime_never_provisions(self):
        with patch.object(runtime, 'provision_runtime') as provision:
            self.assertEqual(runtime.ensure_server(self.cfg).status, 'needs_provision')
            provision.assert_not_called()

    def test_invalid_endpoint_before_probe(self):
        for endpoint in ('http://example.org:11434', 'https://localhost:11434', 'http://localhost:65536'):
            self.assertEqual(runtime.ensure_server({'endpoint': endpoint}).status, 'failed')
        self.probe.assert_not_called()

    def test_external_server_never_stopped(self):
        self.probe.return_value = True
        with patch.object(runtime.os, 'kill') as kill:
            self.assertEqual(runtime.ensure_server(self.cfg).status, 'reachable')
            self.assertFalse(self.manager.spawned_or_adopted())
            self.manager.stop()
            kill.assert_not_called()

    def test_spawn_owned_environment_and_stop(self):
        process = Mock(pid=123)
        process.poll.return_value = None
        self.popen.side_effect = None
        self.popen.return_value = process
        self.manager.spawn('/scratch/ollama', '127.0.0.1:11434')
        self.assertEqual(self.popen.call_args.kwargs['env']['OLLAMA_NO_CLOUD'], '1')
        self.assertEqual(self.popen.call_args.kwargs['env']['OLLAMA_HOST'], '127.0.0.1:11434')
        self.assertTrue(self.manager.spawned_or_adopted())
        self.manager.stop()
        process.terminate.assert_called_once()
        self.assertFalse(os.path.exists(runtime._pidfile_path()))

    def test_occupied_port_saves_endpoint(self):
        self.system.return_value = '/scratch/ollama'
        save = Mock()
        with patch.object(runtime, '_port_in_use', return_value=True), patch.object(runtime, '_free_port', return_value=12345), patch.object(self.manager, 'spawn') as spawn, patch.object(self.manager, 'poll_ready', return_value=(True, '')):
            result = runtime.ensure_server(self.cfg, save)
        self.assertEqual(result.endpoint, 'http://127.0.0.1:12345')
        self.assertTrue(result.port_moved)
        save.assert_called_once_with({'endpoint': result.endpoint})
        spawn.assert_called_once_with('/scratch/ollama', '127.0.0.1:12345')

    def test_ipv6_spawn_matches_endpoint(self):
        self.system.return_value = '/scratch/ollama'
        with patch.object(runtime, '_port_in_use', return_value=False), patch.object(self.manager, 'spawn') as spawn, patch.object(self.manager, 'poll_ready', return_value=(True, '')) as poll:
            result = runtime.ensure_server({'endpoint': 'http://[::1]:11434'})
        self.assertEqual(poll.call_args.args[0], result.endpoint)
        self.assertEqual('http://' + spawn.call_args.args[1], result.endpoint)

    def test_orphan_requires_matching_binary(self):
        os.makedirs(runtime.runtime_root())
        with open(runtime._pidfile_path(), 'w') as f:
            json.dump({'pid': 123, 'host': '127.0.0.1:11434', 'binary': '/scratch/ours'}, f)
        self.probe.return_value = True
        with patch.object(runtime, '_pid_alive', return_value=True), patch.object(runtime, '_process_exe', return_value='/scratch/other'), patch.object(runtime.os, 'kill') as kill:
            self.assertFalse(self.manager.adopt_orphan_if_any(self.cfg['endpoint']))
            self.manager.stop()
            kill.assert_not_called()

    def test_adopted_pid_rechecked_before_stop(self):
        self.manager._adopted_pid = 123
        self.manager._binary = '/scratch/ours'
        with patch.object(runtime, '_pid_alive', return_value=True), patch.object(runtime, '_process_exe', return_value='/scratch/recycled'), patch.object(runtime.os, 'kill') as kill:
            self.manager.stop()
            kill.assert_not_called()

    def test_failed_start_stops_owned_process(self):
        self.system.return_value = '/scratch/ollama'
        with patch.object(runtime, '_port_in_use', return_value=False), patch.object(self.manager, 'spawn'), patch.object(self.manager, 'poll_ready', return_value=(False, 'start failed')), patch.object(self.manager, 'stop') as stop:
            result = runtime.ensure_server(self.cfg)
        self.assertEqual(result.status, 'failed')
        self.assertEqual(result.detail, 'start failed')
        stop.assert_called_once()

    def test_full_setup_is_explicit_provision_path(self):
        with patch.object(runtime, 'platform_kind', return_value='linux'), patch.object(runtime, 'provision_runtime') as provision:
            runtime.full_setup(self.cfg)
        provision.assert_called_once_with(None, None)

    def test_cancelled_setup_and_update_no_install_or_stop(self):
        cancel = threading.Event()
        cancel.set()
        with patch.object(runtime, '_try_winget') as winget, patch.object(runtime, 'provision_runtime') as provision, patch.object(self.manager, 'stop') as stop:
            for action in (runtime.full_setup, runtime.update_runtime):
                with self.assertRaises(runtime.RuntimeProvisionError) as exc:
                    action(self.cfg, cancel_flag=cancel)
                self.assertEqual(exc.exception.kind, 'cancelled')
            winget.assert_not_called()
            provision.assert_not_called()
            stop.assert_not_called()

    def archive(self, member='ollama', symlink=None):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as tf:
            entry = tarfile.TarInfo(member)
            if symlink:
                entry.type = tarfile.SYMTYPE
                entry.linkname = symlink
                tf.addfile(entry)
            else:
                entry.size = 4
                tf.addfile(entry, io.BytesIO(b'fake'))
        return data.getvalue()

    def provision(self, data, sha=None, cancel=None, progress=None):
        asset = runtime.RuntimeAsset('fake.tgz', 'tgz', 10, 10)
        self.network.side_effect = lambda *a, **k: Response(data)
        with patch.object(runtime, 'asset_for_platform', return_value=asset), patch.object(runtime, 'platform_kind', return_value='linux'), patch.object(runtime, 'fetch_expected_sha', return_value=sha or hashlib.sha256(data).hexdigest()):
            return runtime.provision_runtime(cancel_flag=cancel, on_progress=progress)

    def test_successful_archive(self):
        binary = self.provision(self.archive())
        self.assertTrue(os.path.isfile(binary))
        self.assertTrue(os.access(binary, os.X_OK))
        self.assertTrue(os.path.isfile(runtime._complete_marker(runtime.runtime_dir(runtime.OLLAMA_VERSION))))
        self.assertEqual(runtime.find_managed_runtime(), (runtime.OLLAMA_VERSION, binary))

    def test_zip_extraction_and_traversal(self):
        archive = os.path.join(self.tmp.name, 'fixture.zip')
        destination = os.path.join(self.tmp.name, 'zip-runtime')
        asset = runtime.RuntimeAsset('fixture.zip', 'zip', 10, 10)
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr('bin/ollama', b'fake')
        with patch.object(runtime, 'platform_kind', return_value='linux'):
            self.assertEqual(runtime.extract_asset(archive, asset, destination), os.path.join(destination, 'bin/ollama'))
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr('../outside', b'bad')
        with self.assertRaises(runtime.RuntimeProvisionError):
            runtime.extract_asset(archive, asset, destination)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, 'outside')))

    def test_tar_legacy_extraction(self):
        archive = os.path.join(self.tmp.name, 'legacy.tgz')
        with open(archive, 'wb') as f:
            f.write(self.archive())
        original = tarfile.TarFile.extractall
        def legacy(tf, destination, **kwargs):
            if 'filter' in kwargs:
                raise TypeError('unsupported filter')
            return original(tf, destination)
        with patch.object(tarfile.TarFile, 'extractall', legacy), patch.object(runtime, 'platform_kind', return_value='linux'):
            binary = runtime.extract_asset(archive, runtime.RuntimeAsset('legacy.tgz', 'tgz', 10, 10), os.path.join(self.tmp.name, 'legacy'))
        self.assertTrue(os.path.isfile(binary))

    def test_invalid_sha_has_no_marker_or_partial(self):
        with self.assertRaises(runtime.RuntimeProvisionError) as exc:
            self.provision(self.archive(), '0' * 64)
        self.assertEqual(exc.exception.kind, 'checksum')
        self.assertFalse(os.path.exists(runtime._complete_marker(runtime.runtime_dir(runtime.OLLAMA_VERSION))))
        self.assertFalse(os.path.exists(os.path.join(runtime.runtime_root(), 'fake.tgz.part')))

    def test_traversal_and_escaping_link_no_marker(self):
        for name, link in (('../escaped', None), ('link', '../../escaped')):
            data = self.archive(name, link)
            with self.subTest(name=name), patch.object(tarfile.TarFile, 'extractall', side_effect=AssertionError('unsafe extraction attempted')), self.assertRaises(runtime.RuntimeProvisionError):
                self.provision(data)
            self.assertFalse(os.path.exists(runtime._complete_marker(runtime.runtime_dir(runtime.OLLAMA_VERSION))))

    def test_cancelled_download_cleans_partial(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(runtime.RuntimeProvisionError) as exc:
            self.provision(self.archive(), cancel=cancel)
        self.assertEqual(exc.exception.kind, 'cancelled')
        self.assertFalse(os.path.exists(os.path.join(runtime.runtime_root(), 'fake.tgz.part')))
        self.assertFalse(os.path.exists(runtime._complete_marker(runtime.runtime_dir(runtime.OLLAMA_VERSION))))

    def test_cancellation_before_extraction(self):
        cancel = threading.Event()
        def progress(event):
            if event['status'] == 'Extracting runtime':
                cancel.set()
        with patch.object(runtime, 'extract_asset', wraps=runtime.extract_asset) as extract:
            with self.assertRaises(runtime.RuntimeProvisionError) as exc:
                self.provision(self.archive(), cancel=cancel, progress=progress)
            self.assertEqual(exc.exception.kind, 'cancelled')
            extract.assert_not_called()
        self.assertFalse(os.path.exists(runtime.runtime_dir(runtime.OLLAMA_VERSION)))
        self.assertFalse(os.path.exists(os.path.join(runtime.runtime_root(), 'fake.tgz')))

    def test_cancellation_during_extraction(self):
        cancel = threading.Event()
        original = runtime.extract_asset
        def extract(*args):
            result = original(*args)
            cancel.set()
            return result
        with patch.object(runtime, 'extract_asset', side_effect=extract):
            with self.assertRaises(runtime.RuntimeProvisionError) as exc:
                self.provision(self.archive(), cancel=cancel)
            self.assertEqual(exc.exception.kind, 'cancelled')
        self.assertFalse(os.path.exists(runtime.runtime_dir(runtime.OLLAMA_VERSION)))
        self.assertIsNone(runtime.find_managed_runtime())

    def convert_zstd_fixture(self, data, destination, tool='zstd', returncode=0):
        def convert(argv, **kwargs):
            # Only simulate a converter's stdout. Never extract with a tool.
            if kwargs.get('stdout') is not None:
                kwargs['stdout'].write(data)
            return Mock(returncode=returncode, stderr='conversion failed' if returncode else '')
        with patch.object(runtime.shutil, 'which', side_effect=lambda name: '/fake/' + tool if name == tool else None), patch.object(runtime.subprocess, 'run', side_effect=convert):
            runtime._extract_tzst('/scratch/fake.tar.zst', destination)

    def test_zstd_traversal_and_links_rejected_before_extraction(self):
        destination = os.path.join(self.tmp.name, 'zstd')
        os.mkdir(destination)
        for member, link in (('../escaped', None), ('link', '../../escaped')):
            with self.subTest(member=member):
                with self.assertRaises(runtime.RuntimeProvisionError) as exc:
                    self.convert_zstd_fixture(gzip.decompress(self.archive(member, link)), destination)
                self.assertEqual(exc.exception.kind, 'extract')
                self.assertEqual(os.listdir(destination), [])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, 'escaped')))

    def test_zstd_tools_preserve_legitimate_symlinks(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w') as tf:
            entry = tarfile.TarInfo('bin/ollama')
            entry.size = 4
            tf.addfile(entry, io.BytesIO(b'fake'))
            link = tarfile.TarInfo('bin/alias')
            link.type = tarfile.SYMTYPE
            link.linkname = 'ollama'
            tf.addfile(link)
        for tool in ('zstd', 'unzstd', 'bsdtar'):
            destination = os.path.join(self.tmp.name, tool)
            os.mkdir(destination)
            with self.subTest(tool=tool):
                self.convert_zstd_fixture(data.getvalue(), destination, tool)
                with open(os.path.join(destination, 'bin/alias'), 'rb') as f:
                    self.assertEqual(f.read(), b'fake')
                self.assertTrue(os.path.islink(os.path.join(destination, 'bin/alias')))
                self.assertEqual(os.listdir(destination), ['bin'])

    def test_tar_legacy_rechecks_paths_after_symlinks(self):
        destination = os.path.join(self.tmp.name, 'linked')
        os.mkdir(destination)
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w') as tf:
            directory = tarfile.TarInfo('target')
            directory.type = tarfile.DIRTYPE
            tf.addfile(directory)
            link = tarfile.TarInfo('a/link')
            link.type = tarfile.SYMTYPE
            link.linkname = '../target'
            tf.addfile(link)
            entry = tarfile.TarInfo('a/link/../../escaped')
            entry.size = 4
            tf.addfile(entry, io.BytesIO(b'fake'))
        original = tarfile.TarFile.extractall
        def legacy(tf, destination, **kwargs):
            if 'filter' in kwargs:
                raise TypeError('unsupported filter')
            return original(tf, destination)
        with patch.object(tarfile.TarFile, 'extractall', legacy):
            with self.assertRaises(runtime.RuntimeProvisionError):
                self.convert_zstd_fixture(data.getvalue(), destination)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, 'escaped')))

    def test_zstd_conversion_failure_cleans_temporary_tar(self):
        destination = os.path.join(self.tmp.name, 'zstd')
        os.mkdir(destination)
        with self.assertRaises(runtime.RuntimeProvisionError):
            self.convert_zstd_fixture(b'partial', destination, returncode=1)
        self.assertEqual(os.listdir(destination), [])

    def test_zstd_disk_preflight_includes_uncompressed_tar(self):
        asset = runtime.RuntimeAsset('fixture.tar.zst', 'tzst', 10, 20)
        with patch.object(runtime.shutil, 'disk_usage', return_value=Mock(free=runtime._DISK_HEADROOM + 40)):
            with self.assertRaises(runtime.RuntimeProvisionError) as exc:
                runtime.check_disk_space(self.tmp.name, asset)
        self.assertEqual(exc.exception.kind, 'disk')

    def test_platform_selection(self):
        for kind, machine, asset in (('macos', 'arm64', 'ollama-darwin.tgz'), ('windows', 'AMD64', 'ollama-windows-amd64.zip'), ('linux', 'aarch64', 'ollama-linux-arm64.tar.zst')):
            with patch.object(runtime, 'platform_kind', return_value=kind), patch.object(runtime.platform, 'machine', return_value=machine):
                self.assertEqual(runtime.asset_for_platform().name, asset)
        with patch.object(runtime.platform, 'machine', return_value='unsupported'):
            self.assertIsNone(runtime.asset_for_platform())

    def test_disk_space_failure(self):
        with patch.object(runtime.shutil, 'disk_usage', return_value=Mock(free=0)), self.assertRaises(runtime.RuntimeProvisionError) as exc:
            runtime.check_disk_space(self.tmp.name, runtime.RuntimeAsset('fake', 'tgz', 10, 10))
        self.assertEqual(exc.exception.kind, 'disk')


if __name__ == '__main__':
    unittest.main()
