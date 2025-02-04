# To allow users to use arrow keys in the REPL.
import readline  # noqa: F401
import sys
import base64
import tiktoken
import typer
from click import BadArgumentUsage, MissingParameter
from click.types import Choice

from rich import print
from rich.console import Console
from typing import Optional, Literal

from sgpt.config import cfg, print_
from sgpt.handlers.chat_handler import ChatHandler
from sgpt.handlers.default_handler import DefaultHandler
from sgpt.handlers.repl_handler import ReplHandler
from sgpt.role import DefaultRoles, SystemRole
from sgpt.utils import (
    get_edited_prompt,
    get_sgpt_version,
    install_shell_integration,
    run_command,
)


def main(
    prompt: str = typer.Argument(
        None,
        show_default=False,
        help="The prompt to generate completions for.",
    ),
    model: str = typer.Option(
        cfg.get("DEFAULT_MODEL"),
        help="Large language model to use.",
    ),
    temperature: float = typer.Option(
        0.0,
        min=0.0,
        max=2.0,
        help="Randomness of generated output.",
    ),
    top_probability: float = typer.Option(
        1.0,
        min=0.0,
        max=1.0,
        help="Limits highest probable tokens (words).",
    ),
    shell: bool = typer.Option(
        False,
        "--shell",
        "-s",
        help="Generate and execute shell commands.",
        rich_help_panel="Assistance Options",
    ),
    describe_shell: bool = typer.Option(
        False,
        "--describe-shell",
        "-d",
        help="Describe a shell command.",
        rich_help_panel="Assistance Options",
    ),
    code: bool = typer.Option(
        False,
        help="Generate only code.",
        rich_help_panel="Assistance Options",
    ),
    editor: bool = typer.Option(
        False,
        help="Open $EDITOR to provide a prompt.",
    ),
    cache: bool = typer.Option(
        True,
        help="Cache completion results.",
    ),
    version: bool = typer.Option(
        False,
        "--version",
        help="Show version.",
        callback=get_sgpt_version,
    ),
    chat: str = typer.Option(
        None,
        help="Follow conversation with id, " 'use "temp" for quick session.',
        rich_help_panel="Chat Options",
    ),
    image: str = typer.Option(
        None,
        help="Path or URL to image to use as a prompt.",
        rich_help_panel="Chat Options",
    ),
    repl: str = typer.Option(
        None,
        help="Start a REPL (Read–eval–print loop) session.",
        rich_help_panel="Chat Options",
    ),
    tokenize: bool = typer.Option(
        False,
        help="Calculate tokens for prompt.",
    ),
    show_chat: str = typer.Option(
        None,
        help="Show all messages from provided chat id.",
        callback=ChatHandler.show_messages_callback,
        rich_help_panel="Chat Options",
    ),
    list_chats: bool = typer.Option(
        False,
        help="List all existing chat ids.",
        callback=ChatHandler.list_ids,
        rich_help_panel="Chat Options",
    ),
    role: str = typer.Option(
        None,
        help="System role for GPT model.",
        rich_help_panel="Role Options",
    ),
    create_role: str = typer.Option(
        None,
        help="Create role.",
        callback=SystemRole.create,
        rich_help_panel="Role Options",
    ),
    show_role: str = typer.Option(
        None,
        help="Show role.",
        callback=SystemRole.show,
        rich_help_panel="Role Options",
    ),
    list_roles: bool = typer.Option(
        False,
        help="List roles.",
        callback=SystemRole.list,
        rich_help_panel="Role Options",
    ),
    install_integration: bool = typer.Option(
        False,
        help="Install shell integration (ZSH and Bash only)",
        callback=install_shell_integration,
        hidden=True,  # Hiding since should be used only once.
    ),
) -> None:
    stdin_passed = not sys.stdin.isatty()

    if stdin_passed and not repl:
        prompt = f"{sys.stdin.read()}\n\n{prompt or ''}"

    if not prompt and not editor and not repl:
        raise MissingParameter(param_hint="PROMPT", param_type="string")

    if sum((shell, describe_shell, code)) > 1:
        raise BadArgumentUsage(
            "Only one of --shell, --describe-shell, and --code options can be used at a time."
        )

    if chat and repl:
        raise BadArgumentUsage("--chat and --repl options cannot be used together.")

    if editor and stdin_passed:
        raise BadArgumentUsage("--editor option cannot be used with stdin input.")

    image_url = None
    if image:
        # check if correct model is set
        if model != "gpt-4-vision-preview":
            raise BadArgumentUsage("--image prompt requires gpt-4-vision-preview model")

        if "https://" in image or "http://" in image:
            image_url = image
        else:
            # assume it's a path to an image file read and encode to base64
            with open(image, "rb") as image_file:
                image_url = "data:image/jpeg;base64," + base64.b64encode(
                    image_file.read()
                ).decode("utf-8")

    max_tokens = None

    # see: https://platform.openai.com/docs/guides/vision#:~:text=Currently%2C%20GPT%2D4%20Turbo%20with%20vision%20does%20not%20support%20the%20message.name%20parameter%2C%20functions/tools%2C%20response_format%20parameter%2C%20and%20we%20currently%20set%20a%20low%20max_tokens%20default%20which%20you%20can%20override.
    if model in ("gpt-4-vision-preview",):
        max_tokens = 4096

    if editor:
        prompt = get_edited_prompt()

    role_class = (
        DefaultRoles.check_get(shell, describe_shell, code)
        if not role
        else SystemRole.get(role)
    )

    if tokenize:
        encoding = tiktoken.encoding_for_model(model)
        number_of_tokens = len(encoding.encode(prompt))
        print(
            f"Estimated Number of Tokens: [bold red]{number_of_tokens}[/bold red] :boom:"
        )
        return

    if repl:
        # Will be in infinite loop here until user exits with Ctrl+C.
        ReplHandler(repl, role_class).handle(
            prompt,
            model=model,
            temperature=temperature,
            top_p=top_probability,
            chat_id=repl,
            caching=cache,
        )

    if chat:
        full_completion = ChatHandler(chat, role_class).handle(
            prompt,
            image_url=image_url,
            model=model,
            temperature=temperature,
            top_p=top_probability,
            chat_id=chat,
            caching=cache,
            max_tokens=max_tokens,
        )
    else:
        full_completion = DefaultHandler(role_class).handle(
            prompt,
            image_url=image_url,
            model=model,
            temperature=temperature,
            top_p=top_probability,
            caching=cache,
            max_tokens=max_tokens,
        )

    while shell and not stdin_passed:
        option = typer.prompt(
            text="[E]xecute, [D]escribe, [A]bort",
            type=Choice(("e", "d", "a", "y"), case_sensitive=False),
            default="e" if cfg.get("DEFAULT_EXECUTE_SHELL_CMD") == "true" else "a",
            show_choices=False,
            show_default=False,
        )
        if option in ("e", "y"):
            # "y" option is for keeping compatibility with old version.
            run_command(full_completion)
        elif option == "d":
            DefaultHandler(DefaultRoles.DESCRIBE_SHELL.get_role()).handle(
                full_completion,
                model=model,
                image_url=None,
                temperature=temperature,
                top_p=top_probability,
                caching=cache,
            )
            continue
        break


def entry_point() -> None:
    typer.run(main)


if __name__ == "__main__":
    entry_point()
