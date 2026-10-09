"""Full-screen modal prompts (the prompt_toolkit replacement for ``dialog``).

Every prompt returns its answer or raises:

``WizardCancelledError``
    Cancel button, ESC or Ctrl-C.
``GoBackError``
    Back button (only shown when ``Prompt.allow_back`` is set).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar, cast

from prompt_toolkit.application.current import get_app
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Dimension, HSplit, Layout, Window
from prompt_toolkit.widgets import Button, Dialog, TextArea

from .console import AppIo
from .errors import GoBackError, WizardCancelledError
from .logview import InstallProgress
from .theme import build_style, glyphs_for
from .ui import Prompt, YesNoLabels
from .widgets import ChoiceList, ChoiceModel, InlineError, build_application, text_block

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.key_binding import KeyPressEvent
    from prompt_toolkit.layout.containers import AnyContainer

    from .console import Console

WIDTH = Dimension(min=44, preferred=72, max=100)
MIN_BUTTON_WIDTH = 10
BUTTON_PADDING = 4

_T = TypeVar("_T")


def _button(label: str, handler: Callable[[], None]) -> Button:
    """Return a button wide enough for its caption."""
    return Button(label, handler=handler, width=max(MIN_BUTTON_WIDTH, len(label) + BUTTON_PADDING))


class Dialogs:
    """Factory for the wizard's modal prompts, bound to one console."""

    def __init__(self, console: Console, io: AppIo | None = None) -> None:
        """Bind to ``console``; ``io`` overrides input/output (headless tests)."""
        self.console = console
        self.io = io or AppIo()
        self.style = build_style(console.mode)
        self.glyphs = glyphs_for(console.mode)

    # --- plumbing --------------------------------------------------------------

    def _run(self, dialog: Dialog, focus: AnyContainer) -> object:
        """Run a dialog full screen and return what it exits with."""
        self.console.reapply()
        bindings = KeyBindings()

        @bindings.add("escape", eager=True)
        @bindings.add("c-c")
        def _cancel(event: KeyPressEvent) -> None:
            """Cancel the wizard."""
            event.app.exit(exception=WizardCancelledError())

        app = build_application(
            Layout(dialog, focused_element=focus),
            bindings,
            self.console,
            self.style,
            self.io,
        )
        return app.run()

    @staticmethod
    def _exit(*, result: object = None, exc: BaseException | None = None) -> None:
        """End the running dialog with a result or an exception."""
        app = get_app()
        if exc is not None:
            app.exit(exception=exc)
        else:
            app.exit(result=result)

    def _nav_buttons(
        self,
        ok: Button | None,
        *,
        allow_back: bool,
        allow_cancel: bool = True,
    ) -> list[Button]:
        """Return OK (if given) followed by Back and Cancel as requested."""
        buttons = [ok] if ok else []
        if allow_back:
            buttons.append(_button("Back", lambda: self._exit(exc=GoBackError())))
        if allow_cancel:
            buttons.append(_button("Cancel", lambda: self._exit(exc=WizardCancelledError())))
        return buttons

    def _ok_button(self, label: str, handler: Callable[[], None] | None = None) -> Button:
        """Return an OK-style button that confirms the dialog by default."""
        return _button(label, handler or (lambda: self._exit(result=True)))

    @staticmethod
    def _dialog(prompt: Prompt, body: AnyContainer, buttons: list[Button]) -> Dialog:
        """Wrap a body and buttons in the standard framed window."""
        return Dialog(
            title=prompt.title,
            body=body,
            buttons=buttons,
            width=WIDTH,
            with_background=True,
        )

    def _submit(
        self,
        value: _T,
        error: InlineError,
        validate: Callable[[_T], str | None] | None,
    ) -> None:
        """Exit with ``value`` or show the validation message."""
        problem = validate(value) if validate else None
        if problem:
            error.text = problem
            get_app().invalidate()
        else:
            self._exit(result=value)

    # --- prompts ---------------------------------------------------------------

    def msgbox(self, prompt: Prompt, ok: str = "OK") -> None:
        """Show a message and wait for OK (or Back)."""
        ok_button = self._ok_button(ok)
        buttons = [
            ok_button,
            *self._nav_buttons(None, allow_back=prompt.allow_back, allow_cancel=False),
        ]
        self._run(self._dialog(prompt, text_block(prompt.text), buttons), ok_button)

    def yesno(self, prompt: Prompt, labels: YesNoLabels | None = None) -> bool:
        """Ask a yes/no question. No is an answer, not a cancel."""
        labels = labels or YesNoLabels()
        yes_button = _button(labels.yes, lambda: self._exit(result=True))
        no_button = _button(labels.no, lambda: self._exit(result=False))
        buttons = [
            yes_button,
            no_button,
            *self._nav_buttons(None, allow_back=prompt.allow_back, allow_cancel=False),
        ]
        focus = yes_button if labels.default_yes else no_button
        return bool(self._run(self._dialog(prompt, text_block(prompt.text), buttons), focus))

    def menu(
        self,
        prompt: Prompt,
        items: Sequence[tuple[str, str]],
        initial: str | None = None,
    ) -> str:
        """Pick one of ``items`` (value, label); the cursor row is the selection."""
        choice = ChoiceList(ChoiceModel.create(items, multi=False, initial=initial), self.glyphs)

        def accept() -> None:
            """Confirm the row under the cursor."""
            self._exit(result=choice.value())

        choice.on_accept = accept
        ok = self._ok_button("OK", accept)
        buttons = self._nav_buttons(ok, allow_back=prompt.allow_back)
        body = HSplit([text_block(prompt.text), Window(height=1), choice.window])
        return cast("str", self._run(self._dialog(prompt, body, buttons), choice.window))

    def checklist(
        self,
        prompt: Prompt,
        items: Sequence[tuple[str, str]],
        checked: Sequence[str] = (),
        validate: Callable[[list[str]], str | None] | None = None,
    ) -> list[str]:
        """Tick any of ``items``; ``validate`` may veto the selection inline."""
        error = InlineError()
        choice = ChoiceList(ChoiceModel.create(items, multi=True, checked=checked), self.glyphs)
        choice.on_change = lambda: setattr(error, "text", "")

        def accept() -> None:
            """Validate and confirm the ticked rows."""
            self._submit(choice.values(), error, validate)

        choice.on_accept = accept
        buttons = self._nav_buttons(self._ok_button("OK", accept), allow_back=prompt.allow_back)
        body = HSplit(
            [
                text_block(prompt.text),
                Window(height=1),
                choice.window,
                Window(height=1),
                error.container(),
            ]
        )
        result = self._run(self._dialog(prompt, body, buttons), choice.window)
        return cast("list[str]", result)

    def inputbox(
        self,
        prompt: Prompt,
        default: str = "",
        validate: Callable[[str], str | None] | None = None,
    ) -> str:
        """Ask for one line of text; ``validate`` may reject it inline."""
        error = InlineError()

        def accept() -> None:
            """Validate and confirm the typed value."""
            self._submit(field.text.strip(), error, validate)

        def accept_buffer(_buffer: Buffer) -> bool:
            """Handle Enter inside the field and keep the typed text."""
            accept()
            return True

        field = TextArea(
            text=default,
            multiline=False,
            height=1,
            accept_handler=accept_buffer,
            style="class:text-area",
        )
        field.buffer.cursor_position = len(default)
        buttons = self._nav_buttons(self._ok_button("OK", accept), allow_back=prompt.allow_back)
        body = HSplit([text_block(prompt.text), Window(height=1), field, error.container()])
        return cast("str", self._run(self._dialog(prompt, body, buttons), field))

    # --- install run -------------------------------------------------------------

    def run_command(
        self,
        argv: list[str],
        env: dict[str, str],
        title: str,
    ) -> tuple[int, list[str]]:
        """Run ``argv`` with a live log pane. Returns (exit code, last output lines)."""
        progress = InstallProgress(self.console, self.style, title, self.io)
        return progress.run(argv, env)
