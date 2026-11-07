"""Exercise maintenance failure handling using disposable command stubs, not real services."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

__test__ = False
ROOT = Path(__file__).resolve().parent.parent


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sredi-operations-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.log = self.directory / "commands.log"
        self.environment = {
            **os.environ, "PATH": f"{self.directory}:{os.environ['PATH']}", "COMMAND_LOG": str(self.log),
            "RESTIC_REPOSITORY": "s3:https://backup.invalid/test", "RESTIC_PASSWORD": "test-only",
            "POSTGRES_USER": "test-only", "POSTGRES_DB": "test-only", "POSTGRES_PASSWORD": "test-only",
            "BACKUP_STAGING_DIR": str(self.directory / "staging"), "BACKUP_MIN_FREE_BYTES": "0",
        }

    def command(self, name, source):
        import sys
        path = self.directory / name
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o700)

    def run_script(self, script, **environment):
        return subprocess.run(["bash", str(ROOT / "scripts" / script)],
                              env={**self.environment, **environment}, capture_output=True, text=True, timeout=15)

    def test_renewal_reloads_only_after_success_and_configuration_check(self):
        self.command("docker", '''import os, sys
from pathlib import Path
with Path(os.environ["COMMAND_LOG"]).open("a") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
if "certbot" in sys.argv and os.environ.get("FAIL_RENEWAL"):
    sys.exit(1)
''')
        result = self.run_script("renew_certificates.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = self.log.read_text().splitlines()
        self.assertIn("config --quiet", lines[0])
        self.assertIn("run --rm --no-deps certbot", lines[1])
        self.assertIn("nginx -t", lines[2])
        self.assertIn("nginx -s reload", lines[3])
        self.log.write_text("")
        result = self.run_script("renew_certificates.sh", FAIL_RENEWAL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("reload", self.log.read_text())

    def backup_commands(self):
        self.command("psql", '''import os, sys, time
from pathlib import Path
sql = sys.stdin.read()
assert "--set=ON_ERROR_STOP=1" in sys.argv
assert "SET statement_timeout = 0" in sql
assert "pg_try_advisory_lock" in sql
if os.environ.get("LOCK_REFUSED"):
    sys.exit(3)
for line in sql.splitlines():
    if line.startswith("\\\\! touch "):
        Path(line[len("\\\\! touch "):]).touch()
if os.environ.get("LOCK_DIES"):
    time.sleep(0.3)
else:
    time.sleep(60)
''')
        self.command("pg_dump", '''import sys, time
from pathlib import Path
time.sleep(1.5)
Path(next(item.split("=", 1)[1] for item in sys.argv if item.startswith("--file="))).touch()
''')
        self.command("restic", '''import os, sys
from pathlib import Path
with Path(os.environ["COMMAND_LOG"]).open("a") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
if "snapshots" in sys.argv:
    print('[{"short_id":"abc123"}]')
''')

    def test_backup_succeeds_with_live_lock(self):
        self.backup_commands()
        result = self.run_script("backup.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("abc123", result.stdout)
        self.assertIn("backup ", self.log.read_text())

    def test_backup_aborts_when_lock_connection_dies(self):
        self.backup_commands()
        result = self.run_script("backup.sh", LOCK_DIES="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("backup ", self.log.read_text())

    def test_failed_lock_never_starts_dump_or_backup(self):
        self.backup_commands()
        result = self.run_script("backup.sh", LOCK_REFUSED="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.directory / "staging" / "postgres.dump").exists())
        self.assertNotIn("backup ", self.log.read_text())

    def test_local_repository_is_rejected_for_production(self):
        result = self.run_script("backup.sh", RESTIC_REPOSITORY="/data/restic", ALLOW_LOCAL_BACKUP="false")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("off-host", result.stderr)

    def test_restore_verification_rejects_restore_and_query_errors(self):
        for command in ("createdb", "dropdb"):
            self.command(command, "pass\n")
        self.command("restic", '''import os, sys
from pathlib import Path
with Path(os.environ["COMMAND_LOG"]).open("a") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
''')
        self.command("pg_restore", '''import os, sys
assert "--exit-on-error" in sys.argv
sys.exit(1 if os.environ.get("FAIL_RESTORE") else 0)
''')
        self.command("psql", '''import os, sys
assert "--set=ON_ERROR_STOP=1" in sys.argv
sys.exit(1 if os.environ.get("FAIL_QUERY") else 0)
''')
        for failure in ("FAIL_RESTORE", "FAIL_QUERY"):
            with self.subTest(failure=failure):
                self.log.write_text("")
                result = self.run_script("verify_restore.sh", RESTIC_SNAPSHOT_ID="test-snapshot",
                                         RESTORE_MIN_FREE_BYTES="0",
                                         RESTORE_VERIFY_DIR=str(self.directory / "verify"), **{failure: "1"})
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("verification passed", result.stdout)
                self.assertNotIn("check", self.log.read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
