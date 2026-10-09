"""Control-flow exceptions shared by the dialogs and the wizard flow."""


class WizardCancelledError(Exception):
    """User pressed Cancel, ESC or Ctrl-C. Ends the wizard with exit code 0."""


class GoBackError(Exception):
    """User pressed Back. The flow returns to the previous step."""
