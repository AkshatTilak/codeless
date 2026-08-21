import pytest
import pytest_asyncio

from codeless.abb.permissions import TriMode, get_mode_engine
from codeless.jobs.manager import shutdown_task_manager


@pytest.fixture(autouse=True)
def isolate_codeless_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
):

    home_dir = tmp_path_factory.mktemp("codeless_home")
    monkeypatch.setenv("CODELESS_HOME", str(home_dir))
    yield home_dir


@pytest.fixture(autouse=True)
def reset_mode_engine():
    engine = get_mode_engine()
    engine.set_mode(TriMode.AGENT)
    yield
    engine.set_mode(TriMode.AGENT)


@pytest_asyncio.fixture(autouse=True)
async def _reset_background_task_manager():
    yield
    await shutdown_task_manager()
