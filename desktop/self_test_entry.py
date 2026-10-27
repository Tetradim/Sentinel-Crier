"""Avoid modal PyInstaller error dialogs for the explicit offline self-test.

Normal application exceptions retain the regular launch behavior. Self-test
reports include type/stack locations only, never error text, locals or arguments.
"""
import json
from pathlib import Path
import sys
import traceback


def run(main, arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    if '--self-test' not in arguments:
        main()
        return
    try:
        main()
    except Exception as error:
        try:
            index=arguments.index('--report')
            report=Path(arguments[index+1])
            frames=traceback.extract_tb(error.__traceback__,limit=12)
            report.write_text(json.dumps(dict(ok=False,exception_type=type(error).__name__,
                stack=[dict(file=Path(f.filename).name,line=f.lineno,function=f.name) for f in frames])),encoding='utf-8')
        except (ValueError,IndexError,OSError): pass
        raise SystemExit(1) from None
