"""Authored acceptance for the public API introduced by upstream Click PR2563."""
import click
from click.testing import CliRunner


def test_public_help_option_defaults():
    option = click.HelpOption()
    assert isinstance(option, click.Option)
    assert option.opts == ["--help"]
    assert option.is_flag and option.is_eager and not option.expose_value


def test_automatic_help_uses_public_option_and_custom_names():
    command = click.Command("sample", context_settings={"help_option_names": ["-h", "--assist"]})
    with command.make_context("sample", [], resilient_parsing=True) as context:
        option = command.get_help_option(context)
        assert isinstance(option, click.HelpOption)
        assert set(option.opts) == {"-h", "--assist"}
    result = CliRunner().invoke(command, ["--assist"])
    assert result.exit_code == 0 and "Usage:" in result.output


def test_decorator_and_direct_option_have_equivalent_default_behavior():
    @click.command(add_help_option=False)
    @click.help_option("--assist")
    def decorated():
        raise AssertionError("Help must exit before invoking the command")

    direct = click.Command("direct", params=[click.HelpOption(["--assist"])])
    assert isinstance(decorated.params[0], click.HelpOption)
    for command in [decorated, direct]:
        result = CliRunner().invoke(command, ["--assist"])
        assert result.exit_code == 0 and "Usage:" in result.output


def test_help_option_respects_explicit_callback_override():
    def custom(context, parameter, value):
        if value:
            click.echo("custom help")
            context.exit()

    command = click.Command("sample", params=[click.HelpOption(callback=custom)], add_help_option=False)
    result = CliRunner().invoke(command, ["--help"])
    assert result.exit_code == 0 and result.output == "custom help\n"


def test_help_option_decorator_preserves_custom_class():
    class CustomHelp(click.HelpOption):
        pass

    @click.command(add_help_option=False)
    @click.help_option("--assist", cls=CustomHelp)
    def command():
        pass

    assert isinstance(command.params[0], CustomHelp)
    assert CliRunner().invoke(command, ["--assist"]).exit_code == 0


def test_disabling_automatic_help_is_preserved():
    for command in [click.Command("sample", add_help_option=False),
                    click.Command("sample", context_settings={"help_option_names": []})]:
        with command.make_context("sample", [], resilient_parsing=True) as context:
            assert command.get_help_option(context) is None
