"""Placed at the repository root so ``pytest -q`` puts the root on sys.path
and ``import calculators`` resolves without an editable install."""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "subprocess: spawns the MCP server as a child process. Everything "
        "else in the suite runs in one interpreter with no I/O.",
    )
