import sys


def is_debugging() -> bool:
    """
    If we are debugging using e.g. vscode, joblib needs to be prevented from
    creating subprocesses as this crashes during loading of C libraries.
    """
    try:
        if sys.gettrace() is not None:
            return True
    except AttributeError:
        pass

    try:
        if sys.monitoring.get_tool(sys.monitoring.DEBUGGER_ID) is not None:
            return True
    except AttributeError:
        pass

    return False
