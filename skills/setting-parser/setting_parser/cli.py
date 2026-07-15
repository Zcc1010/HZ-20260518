"""CLI 入口：parse / stats / describe / kb."""
import typer


def _root(ctx: typer.Context) -> None:
    """空回调：让 Typer 0.20+ 在没有任何子命令时也能正常产生 Click Command."""
    pass


app = typer.Typer(
    name="setting-parser",
    help="调度定值单解析 CLI 工具",
    no_args_is_help=True,
    callback=_root,
)

# parse / stats / describe 直接注册为命令（不走 sub-app，便于选项在位置参数前后灵活排列）
from setting_parser.subcommands.parse import parse_cmd  # noqa: E402
from setting_parser.subcommands.stats_cmd import stats_cmd  # noqa: E402
from setting_parser.subcommands.describe import describe_cmd  # noqa: E402

app.command(name="parse")(parse_cmd)
app.command(name="stats")(stats_cmd)
app.command(name="describe")(describe_cmd)

# kb 用 sub-app（包含 list / lookup 等子命令）
from setting_parser.subcommands.kb import app as kb_app  # noqa: E402

app.add_typer(kb_app, name="kb")


if __name__ == "__main__":
    app()
