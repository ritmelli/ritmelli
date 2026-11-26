from pathlib import Path

from syntax import yaml

ROOT = Path(__file__).resolve().parent.parent
YamlError = yaml.YamlError


def loads(text, name="<yaml>"):
    return yaml.loads(text, name)


def load(path):
    path = Path(path)
    return loads(path.read_text(encoding="utf-8"), str(path))


def workflows(root=ROOT):
    root = Path(root)
    found = sorted(p for p in (root / ".github" / "workflows").iterdir() if p.suffix in (".yml", ".yaml"))
    return {p.relative_to(root).as_posix(): load(p) for p in found}


def job_steps(job):
    return job.get("steps") or []


def find_step(job, name):
    found = [s for s in job_steps(job) if s.get("name") == name]
    return found[0] if len(found) == 1 else None
