"""Local window and server for the stock agent."""


def main(argv: list[str] | None = None) -> None:
    from stock_agent.ui.__main__ import main as run

    run(argv)
