"""Compose regression checks; --smoke additionally boots a disposable production stack."""

import argparse
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = ROOT / "docker-compose.prod.yml"
EXAMPLE_FILE = ROOT / ".env.production.example"
# These checks require the Docker CLI and run separately from the Django pytest suite.
__test__ = False


def example_environment():
    return dict(
        line.split("=", 1)
        for line in EXAMPLE_FILE.read_text().splitlines()
        if line and not line.startswith("#")
    )


def isolated_environment():
    deployment_keys = set(example_environment()) | {"ENV_FILE"}
    return {
        key: value for key, value in os.environ.items()
        if key not in deployment_keys and not key.startswith("COMPOSE_")
    }


def write_environment(path, values):
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
    path.chmod(0o600)


class ProductionComposeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sredi-config-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        shutil.copyfile(COMPOSE_FILE, self.directory / COMPOSE_FILE.name)
        # Both possible accidental sources contain distinct, deliberately wrong values.
        for name in (".env", ".env.production.example"):
            write_environment(self.directory / name, {
                "DOMAIN": "wrong-source.invalid", "CERTBOT_EMAIL": "wrong@source.invalid",
                "POSTGRES_PASSWORD": "wrong-source-password",
            })
        self.values = {
            **example_environment(),
            "DOMAIN": "config-check.invalid",
            "CERTBOT_EMAIL": "ops@config-check.invalid",
            "POSTGRES_PASSWORD": "config-check-password",
            "DJANGO_ALLOWED_HOSTS": "config-check.invalid",
            "CSRF_TRUSTED_ORIGINS": "https://config-check.invalid",
        }

    def render(self, values, filename=".env.production"):
        selected = self.directory / filename
        write_environment(selected, values)
        environment = isolated_environment()
        if filename != ".env.production":
            environment["ENV_FILE"] = str(selected)
        return subprocess.run(
            ["docker", "compose", "--env-file", str(selected), "-f",
             str(self.directory / COMPOSE_FILE.name), "--profile", "tools", "config", "--format", "json"],
            cwd=self.directory, env=environment, capture_output=True, text=True, check=False,
        )

    def test_selected_file_supplies_interpolation_and_container_environment(self):
        for filename in (".env.production", "custom.env"):
            with self.subTest(filename=filename):
                result = self.render(self.values, filename)
                self.assertEqual(result.returncode, 0, result.stderr)
                services = json.loads(result.stdout)["services"]
                self.assertEqual(services["nginx"]["environment"]["DOMAIN"], self.values["DOMAIN"])
                self.assertEqual(services["certbot-issue"]["environment"]["CERTBOT_EMAIL"], self.values["CERTBOT_EMAIL"])
                for service in ("app", "migrate", "db", "worker", "beat", "backup", "restore", "restore-verify"):
                    self.assertEqual(services[service]["environment"]["POSTGRES_PASSWORD"], self.values["POSTGRES_PASSWORD"])
                    self.assertEqual(services[service]["environment"]["DOMAIN"], self.values["DOMAIN"])

    def test_required_variables_fail_before_startup(self):
        for key in ("DOMAIN", "CERTBOT_EMAIL"):
            for missing in (True, False):
                with self.subTest(key=key, missing=missing):
                    values = dict(self.values)
                    if missing:
                        values.pop(key)
                    else:
                        values[key] = ""
                    result = self.render(values)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f"Set {key}", result.stderr)


def smoke_test():
    project = f"sredi-startup-test-{secrets.token_hex(6)}"
    domain = "sredi-startup.invalid"
    with tempfile.TemporaryDirectory(prefix="sredi-startup-test-") as temporary:
        directory = Path(temporary)
        certificate_directory = directory / "certificates" / "live" / domain
        certificate_directory.mkdir(parents=True)
        certificate = certificate_directory / "fullchain.pem"
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", f"/CN={domain}", "-addext", f"subjectAltName=DNS:{domain}",
            "-keyout", str(certificate_directory / "privkey.pem"), "-out", str(certificate),
        ], check=True, capture_output=True)
        certificate.chmod(0o644)
        env_file = directory / "production.env"
        write_environment(env_file, {
            **example_environment(),
            "DOMAIN": domain,
            "DJANGO_ALLOWED_HOSTS": domain,
            "CSRF_TRUSTED_ORIGINS": f"https://{domain}",
            "DJANGO_SECRET_KEY": secrets.token_hex(32),
            "POSTGRES_PASSWORD": secrets.token_hex(24),
            "POSTGRES_DB": "sredi_startup_test",
            "RESTIC_PASSWORD": secrets.token_hex(24),
            "CERTBOT_EMAIL": f"ops@{domain}",
            "EMAIL_HOST": "smtp-not-started.invalid",
        })
        override = directory / "smoke.yml"
        delayed_dump = directory / "backup-bin"
        delayed_dump.mkdir()
        (delayed_dump / "pg_dump").write_text("#!/bin/sh\nsleep 16\nexec /usr/bin/pg_dump \"$@\"\n")
        (delayed_dump / "pg_dump").chmod(0o755)
        # !reset removes production port mappings; only this project's private network is used.
        override.write_text(
            "services:\n"
            "  app:\n"
            "    environment:\n"
            '      STARTUP_SMOKE_TEST: "1"\n'
            "    volumes:\n"
            f"      - {json.dumps(str(certificate) + ':/tmp/startup-ca.pem:ro')}\n"
            "  worker:\n"
            "    environment:\n"
            "      EMAIL_BACKEND: django.core.mail.backends.locmem.EmailBackend\n"
            "  backup:\n"
            "    environment:\n"
            "      RESTIC_REPOSITORY: /data/restic\n"
            '      ALLOW_LOCAL_BACKUP: "true"\n'
            "    volumes:\n"
            f"      - {json.dumps(str(delayed_dump) + ':/test-backup-bin:ro')}\n"
            "  restore-verify:\n"
            "    environment:\n"
            "      RESTIC_REPOSITORY: /data/restic\n"
            "  nginx:\n"
            "    ports: !reset []\n"
            "    volumes:\n"
            f"      - {json.dumps(str(directory / 'certificates') + ':/etc/letsencrypt:ro')}\n"
            "    healthcheck:\n"
            '      test: ["CMD", "nginx", "-t"]\n'
            "      interval: 2s\n"
            "      timeout: 5s\n"
            "      retries: 10\n"
        )
        environment = {**isolated_environment(), "ENV_FILE": str(env_file)}
        compose = ["docker", "compose", "--env-file", str(env_file), "-p", project,
                   "-f", str(COMPOSE_FILE), "-f", str(override)]

        def run(*arguments, capture=False, check=True):
            return subprocess.run(
                [*compose, *arguments], cwd=ROOT, env=environment, check=check,
                text=True, capture_output=capture,
            )

        run("config", "--quiet")
        try:
            print(f"Starting isolated production smoke test: {project}", flush=True)
            run("up", "--build", "--wait", "--wait-timeout", "180", "nginx", "worker")
            result = run(
                "exec", "-T", "app", "curl", "--fail", "--silent", "--show-error", "--max-time", "10",
                "--cacert", "/tmp/startup-ca.pem", "--connect-to", f"{domain}:443:nginx:443",
                f"https://{domain}/health/ready/", capture=True,
            )
            payload = json.loads(result.stdout)
            if payload.get("status") != "ready":
                raise RuntimeError("HTTPS readiness did not report ready")
            for dependency in ("database", "migrations", "redis"):
                if payload["dependencies"][dependency] != "ok":
                    raise RuntimeError(f"Readiness dependency failed: {dependency}")
            rejected = run(
                "exec", "-T", "app", "curl", "--silent", "--max-time", "5", "--output", "/dev/null",
                "--write-out", "%{http_code}", "--header", "X-Forwarded-Proto: https",
                "http://localhost:8000/health/ready/", capture=True,
            )
            if rejected.stdout != "400":
                raise RuntimeError("The localhost Host must remain rejected")
            print("Production startup passed: app healthy, Nginx HTTPS ready, localhost rejected.", flush=True)
            run("exec", "-T", "app", "python", "scripts/production_probe.py", "load", "--domain", domain)
            run("stop", "redis")
            try:
                run("exec", "-T", "app", "python", "scripts/production_probe.py", "outage", "--domain", domain)
            finally:
                run("up", "--wait", "--wait-timeout", "60", "redis")
            run("up", "--wait", "--wait-timeout", "120", "nginx", "worker")
            print("Redis restart recovered application readiness.", flush=True)
            # A real backup lasting beyond PostgreSQL's former 15-second timeout.
            run("run", "--build", "--rm", "--no-deps", "--entrypoint", "bash", "backup", "-c",
                'export PATH="/test-backup-bin:$PATH"; export PGOPTIONS="-c statement_timeout=15000"; exec /scripts/backup.sh')
            snapshots = run("run", "--rm", "--no-deps", "--entrypoint", "restic", "backup",
                            "snapshots", "--json", capture=True)
            snapshot = json.loads(snapshots.stdout)[0]["id"]
            run("run", "--build", "--rm", "--no-deps", "-e", f"RESTIC_SNAPSHOT_ID={snapshot}", "restore-verify")
            print("Real backup held its lock beyond 15 seconds; encrypted snapshot restore verification passed.", flush=True)
        except BaseException:
            run("logs", "--no-color", "--tail", "60", "app", "migrate", "nginx", check=False)
            raise
        finally:
            # The project name is generated here; never remove a developer/production project's volumes.
            run("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    arguments = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ProductionComposeTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    if arguments.smoke:
        smoke_test()
