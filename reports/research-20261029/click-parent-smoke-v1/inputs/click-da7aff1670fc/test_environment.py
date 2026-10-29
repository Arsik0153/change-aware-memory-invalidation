import click
from click.testing import CliRunner


def test_echo_invocation():
    @click.command()
    def hello():
        click.echo("cami-pilot")
    result = CliRunner().invoke(hello, [])
    assert result.exit_code == 0
    assert result.output == "cami-pilot\n"
