"""PyInstaller entry-point script.

Called by PyInstaller to bootstrap the frozen application.
Allows ``aisc.cli.main:main`` to work correctly in a onefile build.
"""

from aisc.cli.main import main

if __name__ == "__main__":
    main()
