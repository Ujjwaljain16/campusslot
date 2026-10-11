"""Tests of scripts/promote.py. They use a throw-away git repository, so the rules are tested the way CI runs them.

    python3 -m unittest discover -s scripts/tests -v
"""

import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "promote.py"
spec = importlib.util.spec_from_file_location("promote", SCRIPT)
promote = importlib.util.module_from_spec(spec)
sys.modules["promote"] = promote
spec.loader.exec_module(promote)

A = "a" * 40
B = "b" * 40
C = "c" * 40

TEMPLATE = """# The {env} environment.
backend:
  image:
    tag: "{tag}"
  replicaCount: 1
  env:
    APP_ENV: development
frontend:
  image:
    tag: "{tag}"
  replicaCount: 1

ingress:
  host: {env}.campusslot.test
"""


class Repo:
    """A git repository with the three environment files, as the CI checkout of a pull request would have them."""

    def __init__(self, directory: Path):
        self.root = directory
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "test")
        for env in promote.ENVS:
            self.write(env, A)
        self.commit("base")
        self.git("branch", "base")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, check=True).stdout

    def write(self, env, tag, frontend=None):
        path = self.root / "gitops" / "envs" / env / "values.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        text = TEMPLATE.format(env=env, tag=tag)
        if frontend:
            text = text.replace(f'tag: "{tag}"', f'tag: "{frontend}"', 2).replace(f'tag: "{frontend}"', f'tag: "{tag}"', 1)
        path.write_text(text, encoding="utf-8")

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def check(self, base="base"):
        promote.ROOT = self.root
        out = io.StringIO()
        with redirect_stdout(out):
            code = promote.check(type("Args", (), {"base": base})())
        return code, out.getvalue()


class ParseTests(unittest.TestCase):
    def test_the_tags_are_read_from_the_image_blocks_only(self):
        text = TEMPLATE.format(env="dev", tag=A)
        self.assertEqual(promote.read_tags(text), {"backend": A, "frontend": A})

    def test_a_tag_elsewhere_is_not_an_image_tag(self):
        text = TEMPLATE.format(env="dev", tag=A) + "\ntracing:\n  tag: \"not-an-image\"\n"
        self.assertEqual(promote.read_tags(text), {"backend": A, "frontend": A})

    def test_writing_changes_both_tags_and_nothing_else(self):
        text = TEMPLATE.format(env="staging", tag=A)
        new = promote.write_tags(text, B)
        self.assertEqual(promote.read_tags(new), {"backend": B, "frontend": B})
        self.assertEqual(new.replace(B, A), text)  # the rest, with its comments, is byte for byte the same


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(Path(self.tmp.name))

    def tearDown(self):
        promote.ROOT = SCRIPT.parent.parent
        self.tmp.cleanup()

    def test_no_change_is_fine(self):
        code, _ = self.repo.check()
        self.assertEqual(code, 0)

    def test_dev_takes_a_commit_that_exists(self):
        real = self.repo.git("rev-parse", "HEAD").strip()
        self.repo.write("dev", real)
        self.repo.commit("promote to dev")
        code, out = self.repo.check()
        self.assertEqual(code, 0, out)

    def test_dev_cannot_take_a_commit_that_does_not_exist(self):
        self.repo.write("dev", B)
        self.repo.commit("promote to dev")
        code, out = self.repo.check()
        self.assertEqual(code, 1)
        self.assertIn("does not exist", out)

    def test_staging_cannot_skip_dev(self):
        self.repo.write("staging", B)
        self.repo.commit("promote to staging")
        code, out = self.repo.check()
        self.assertEqual(code, 1)
        self.assertIn("one step at a time", out)

    def test_staging_takes_what_dev_runs_at_the_base(self):
        self.repo.write("dev", B)
        self.repo.commit("dev runs B")
        self.repo.git("branch", "-f", "base")
        self.repo.write("staging", B)
        self.repo.commit("promote to staging")
        code, out = self.repo.check()
        self.assertEqual(code, 0, out)

    def test_dev_and_staging_cannot_move_together_in_one_pull_request(self):
        # staging would take a build that dev has not run at the base of the pull request
        self.repo.write("dev", B)
        self.repo.write("staging", B)
        self.repo.commit("both")
        code, out = self.repo.check()
        self.assertEqual(code, 1)
        self.assertIn("staging", out)

    def test_prod_cannot_skip_staging(self):
        self.repo.write("prod", B)
        self.repo.commit("promote to prod")
        code, _ = self.repo.check()
        self.assertEqual(code, 1)

    def test_prod_takes_what_staging_runs(self):
        self.repo.write("staging", B)
        self.repo.commit("staging runs B")
        self.repo.git("branch", "-f", "base")
        self.repo.write("prod", B)
        self.repo.commit("promote to prod")
        code, out = self.repo.check()
        self.assertEqual(code, 0, out)

    def test_a_prod_promotion_changes_nothing_else(self):
        self.repo.write("staging", B)
        self.repo.commit("staging runs B")
        self.repo.git("branch", "-f", "base")
        self.repo.write("prod", B)
        self.repo.write("dev", C)  # an unrelated change in the same pull request
        self.repo.commit("prod and more")
        code, out = self.repo.check()
        self.assertEqual(code, 1)
        self.assertIn("nothing else", out)

    def test_the_backend_and_the_frontend_must_run_the_same_commit(self):
        self.repo.write("dev", A, frontend=B)
        self.repo.commit("uneven")
        code, out = self.repo.check()
        self.assertEqual(code, 1)
        self.assertIn("different commits", out)

    def test_a_branch_name_or_latest_is_not_a_tag(self):
        self.repo.write("dev", "latest")
        self.repo.commit("latest")
        code, out = self.repo.check()
        self.assertEqual(code, 1)
        self.assertIn("not a full commit hash", out)


class PromoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(Path(self.tmp.name))
        promote.ROOT = self.repo.root

    def tearDown(self):
        promote.ROOT = SCRIPT.parent.parent
        self.tmp.cleanup()

    def run_promote(self, to, sha=None):
        out = io.StringIO()
        with redirect_stdout(out):
            code = promote.promote(type("Args", (), {"to": to, "sha": sha})())
        return code, out.getvalue()

    def test_dev_needs_a_commit(self):
        with self.assertRaises(SystemExit):
            self.run_promote("dev")

    def test_staging_copies_the_tags_of_dev(self):
        (self.repo.root / "gitops/envs/dev/values.yaml").write_text(TEMPLATE.format(env="dev", tag=B), encoding="utf-8")
        self.run_promote("staging")
        staging = promote.read_tags((self.repo.root / "gitops/envs/staging/values.yaml").read_text(encoding="utf-8"))
        self.assertEqual(staging, {"backend": B, "frontend": B})

    def test_staging_refuses_a_commit_that_dev_does_not_run(self):
        with self.assertRaises(SystemExit):
            self.run_promote("staging", sha=B)

    def test_promoting_what_is_already_there_changes_nothing(self):
        before = (self.repo.root / "gitops/envs/staging/values.yaml").read_text(encoding="utf-8")
        _, out = self.run_promote("staging")
        self.assertIn("nothing to do", out)
        self.assertEqual((self.repo.root / "gitops/envs/staging/values.yaml").read_text(encoding="utf-8"), before)


class AppSetTests(unittest.TestCase):
    def appset(self, envs):
        out = io.StringIO()
        promote.ROOT = SCRIPT.parent.parent
        with redirect_stdout(out):
            promote.appset(type("Args", (), {"envs": envs, "revision": None})())
        return out.getvalue()

    def test_only_the_wanted_environments_remain(self):
        text = self.appset("dev,staging")
        self.assertIn("- env: dev", text)
        self.assertIn("- env: staging", text)
        self.assertNotIn("- env: prod", text)

    def test_every_remaining_element_keeps_its_sync_setting(self):
        text = self.appset("dev,prod")
        self.assertIn('- env: dev\n            autoSync: "true"', text.replace("\r\n", "\n"))
        self.assertIn('- env: prod\n            autoSync: "false"', text.replace("\r\n", "\n"))
        self.assertEqual(text.count("autoSync:"), 2)

    def test_an_unknown_environment_is_refused(self):
        with self.assertRaises(SystemExit):
            self.appset("dev,qa")


if __name__ == "__main__":
    unittest.main()
