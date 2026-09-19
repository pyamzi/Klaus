"""Behavioral tests for the local whisper.cpp adapter."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, ".claude/skills/klaus-test/scripts")
from anki_stubs import check, install, report, section

install()
lt = importlib.import_module("klausmate.local_transcription")


def fails(label, action, words):
    try:
        action()
    except lt.TranscriptionError as exc:
        message = exc.user_message()
        check(label, all(word in message.lower() for word in words))
        check(label + " keeps private output private", "SECRET" not in str(exc))
    else:
        check(label, False)


with tempfile.TemporaryDirectory(prefix="local transcription tests ") as directory:
    root = Path(directory)
    fake = root / "whisper executable"
    model = root / "model file.bin"
    model.write_bytes(b"fixture")
    record = root / "argv.json"

    def executable(mode="ok"):
        fake.write_text("#!" + sys.executable + "\n" +
            "import json,pathlib,sys,time\n" +
            "a=sys.argv; p=a[a.index('-of')+1]\n" +
            "assert '-oj' in a and a[a.index('-l')+1]=='en'\n" +
            "assert pathlib.Path(a[a.index('-f')+1]).read_bytes()==b'fixture WAV'\n" +
            "pathlib.Path(" + repr(str(record)) + ").write_text(json.dumps(a))\n" +
            "mode=" + repr(mode) + "\n" +
            "if mode=='exit': sys.stderr.write('SECRET'); sys.exit(1)\n" +
            "if mode=='timeout': time.sleep(2)\n" +
            "if mode=='absent': sys.exit(0)\n" +
            "data={'transcription':[{'text':' hello '},{'text':'  '},{'text':'world'}]}\n" +
            "if mode=='empty': data={'transcription':[]}\n" +
            "if mode=='shape': data={'transcription':[{'text':42}]}\n" +
            "if mode=='missing': data={}\n" +
            "if mode=='root': data=[]\n" +
            "if mode=='segment': data={'transcription':['SECRET']}\n" +
            "pathlib.Path(p+'.json').write_text('SECRET' if mode=='invalid' else json.dumps(data))\n")
        fake.chmod(0o755)

    def transcribe(**kwargs):
        return lt.transcribe(b"fixture WAV", str(model), binary=str(fake), **kwargs)

    section("real subprocess behavior")
    executable()
    prompt = 'slide words; $(echo SECRET) "quoted"'
    check("JSON segments joined", transcribe(prompt=prompt) == "hello world")
    argv = json.loads(record.read_text())
    check("paths with spaces preserved", argv[0] == str(fake) and argv[argv.index('-m') + 1] == str(model))
    check("prompt is one literal argv value", argv[argv.index('--prompt') + 1] == prompt)
    check("private temporary WAV removed", not Path(argv[argv.index('-f') + 1]).parent.exists())
    executable("empty")
    check("empty transcription returns empty string", transcribe() == "")
    for mode, words in [("exit", ["whisper.cpp", "model"]), ("absent", ["json"]),
                        ("invalid", ["json"]), ("shape", ["json"]),
                        ("missing", ["json"]), ("root", ["json"]), ("segment", ["json"]),
                        ("timeout", ["timed out"] )]:
        executable(mode)
        fails(mode, lambda: transcribe(timeout=0.1 if mode == "timeout" else 10), words)
        argv = json.loads(record.read_text())
        check(mode + " cleans temporary output", not Path(argv[argv.index('-of') + 1]).parent.exists())

    section("validation and safe errors")
    executable()
    with patch.object(lt.subprocess, "run") as run:
        fails("missing model", lambda: lt.transcribe(b"x", str(root / 'missing'), binary=str(fake)), ["model", "preferences"])
        fails("directory model", lambda: lt.transcribe(b"x", str(root), binary=str(fake)), ["model", "preferences"])
        fails("missing binary", lambda: lt.transcribe(b"x", str(model), binary=str(root / 'missing')), ["whisper.cpp", "preferences"])
        fake.chmod(0o644)
        fails("not executable", transcribe, ["whisper.cpp"])
        check("invalid paths never spawn", not run.called)
    executable()
    with patch.object(lt.subprocess, "run", side_effect=OSError("SECRET")):
        fails("OS failure", transcribe, ["whisper.cpp"])

    fails("invalid argv", lambda: transcribe(prompt="bad\0argument"), ["whisper.cpp"])

    section("discovery")
    with patch.object(lt.shutil, "which", return_value=str(fake)) as which, patch.object(lt.subprocess, "run") as run:
        check("PATH discovery", lt.find_binary() == str(fake))
        check("preferred binary name", which.call_args.args == ("whisper-cli",))
        check("PATH avoids shell", not run.called)
        check("invalid explicit override has no fallback", lt.find_binary(str(root / 'missing')) is None)
        check("explicit path with spaces", lt.find_binary(str(fake)) == str(fake))
    with patch.object(lt.shutil, "which", side_effect=lambda name: str(fake) if name == 'whisper-cpp' else None):
        check("alternate PATH binary", lt.find_binary() == str(fake))
    with patch.object(lt.shutil, "which", return_value=None), patch.object(lt.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, str(fake) + '\n', '')) as run:
        check("login shell discovery", lt.find_binary() == str(fake))
        args, kwargs = run.call_args
        check("fixed login shell command", args[0][-2:] == ['-lc', 'command -v whisper-cli || command -v whisper-cpp'])
        check("shell discovery is bounded", 0 < kwargs['timeout'] <= 5)
    with patch.object(lt.shutil, "which", return_value=None), patch.object(lt.subprocess, "run", side_effect=subprocess.TimeoutExpired('shell', 3)), patch.object(lt, "_KNOWN_PATHS", (str(fake),)):
        check("known path after shell timeout", lt.find_binary() == str(fake))
    with patch.object(lt.shutil, "which", return_value=None) as which, patch.object(lt.subprocess, "run", side_effect=OSError()), patch.object(lt, "_KNOWN_PATHS", ()):
        check("absent binary returns None", lt.find_binary() is None)
        check("generic main never searched", all(call.args != ('main',) for call in which.call_args_list))
    main = root / 'main'
    main.write_text('#!/bin/sh\nexit 0\n')
    main.chmod(0o755)
    check("explicit main accepted", lt.find_binary(str(main)) == str(main))

raise SystemExit(report())
