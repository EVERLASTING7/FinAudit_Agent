import warnings
from itertools import pairwise
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_migration_graph_is_one_complete_linear_chain() -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        scripts = ScriptDirectory.from_config(config)
        bases = scripts.get_bases()
        heads = scripts.get_heads()
        revisions = list(scripts.walk_revisions(base="base", head="heads"))

    assert len(bases) == 1, bases
    assert len(heads) == 1, heads
    assert revisions
    assert revisions[0].revision == heads[0]
    assert revisions[-1].revision == bases[0]
    assert revisions[-1].down_revision is None
    assert [revision.revision for revision in revisions if revision.is_branch_point] == []
    assert [revision.revision for revision in revisions if revision.is_merge_point] == []
    assert [revision.revision for revision in revisions if revision.dependencies] == []
    assert all(newer.down_revision == older.revision for newer, older in pairwise(revisions))
